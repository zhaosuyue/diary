#!/usr/bin/env python3
"""
Build diary site from Redoc docs.
Pulls content from Redoc via hi-workspace-cli, generates static JSON,
then writes index.html with the data embedded.

Usage:
  python3 build.py
  
Then push dist/ (or the root) to GitHub.
"""
import os, re, json, subprocess, sys, urllib.request, urllib.parse
from datetime import datetime

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DIST_DIR     = os.path.join(SCRIPT_DIR, 'dist')
OUTPUT_PATH  = os.path.join(DIST_DIR, 'index.html')
DATA_PATH    = os.path.join(DIST_DIR, 'diary-data.json')

INDEX_DOC_ID = 'e242211844eb2e09e9b775da28fc9f47'
CLI = 'bunx @xhs/hi-workspace-cli@0.2.7'

WEEKDAY_MAP = {'Monday':'周一','Tuesday':'周二','Wednesday':'周三',
               'Thursday':'周四','Friday':'周五','Saturday':'周六','Sunday':'周日'}


def run_cli(shortcut_id):
    """Run docs:get and return parsed JSON dict."""
    cmd = f'{CLI} docs:get --shortcut-id {shortcut_id}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                            cwd=SCRIPT_DIR)
    if result.returncode != 0:
        raise RuntimeError(f'CLI failed for {shortcut_id}: {result.stderr[:200]}')
    return json.loads(result.stdout)


def fetch_apple_music_cover(apple_url):
    """Given an Apple Music URL, return a 600x600 cover image URL or None."""
    # extract numeric album/song id from URL
    m = re.search(r'/(\d{6,12})(?:\?|$)', apple_url)
    if not m:
        # search URL — try to extract term and query iTunes
        term_m = re.search(r'[?&]term=([^&]+)', apple_url)
        if not term_m:
            return None
        term = urllib.parse.unquote_plus(term_m.group(1))
        api_url = f'https://itunes.apple.com/search?term={urllib.parse.quote(term)}&media=music&entity=album&limit=1&country=cn'
        try:
            with urllib.request.urlopen(api_url, timeout=8) as r:
                data = json.loads(r.read())
            results = data.get('results', [])
            if results:
                art = results[0].get('artworkUrl100', '')
                return art.replace('100x100bb', '600x600bb') if art else None
        except:
            return None
        return None

    item_id = m.group(1)
    # try as album first, then song
    for entity in ('album', 'song'):
        api_url = f'https://itunes.apple.com/lookup?id={item_id}&entity={entity}&country=cn'
        try:
            with urllib.request.urlopen(api_url, timeout=8) as r:
                data = json.loads(r.read())
            results = data.get('results', [])
            for item in results:
                art = item.get('artworkUrl100', '')
                if art:
                    return art.replace('100x100bb', '600x600bb')
        except:
            continue
    return None


def parse_index(content):
    """Parse main doc → list of (id, date, title)."""
    entries = []
    # Pattern: #### [DATE TITLE](URL)
    re_entry = re.compile(
        r'####\s+\[(\d{4}-\d{2}-\d{2})\s+(?:周[一二三四五六日]\s+—\s+)?([^\]]+)\]'
        r'\(https://docs\.xiaohongshu\.com/doc/([a-f0-9]+)\)'
    )
    for m in re_entry.finditer(content):
        date_str = m.group(1)
        title    = m.group(2).strip()
        doc_id   = m.group(3)
        entries.append({'id': doc_id, 'date': date_str, 'title': title})
    return entries


def redoc_md_to_html(md, cover_cache=None):
    """Convert Redoc-flavored markdown to plain HTML."""
    if not md: return ''
    if cover_cache is None: cover_cache = {}

    # strip font color tags (date line)
    md = re.sub(r'<font[^>]*>(.*?)</font>', r'<span class="entry-meta">\1</span>', md, flags=re.DOTALL)

    # redoc-highlight blocks
    def highlight_block(m):
        full_tag = m.group(0)
        emoji_name = re.search(r'emoji="([^"]+)"', full_tag)
        emoji_key = emoji_name.group(1) if emoji_name else ''
        emoji = {'yueliang': '🎵', 'tuding': '📌'}.get(emoji_key, '•')
        inner = m.group(1).strip()

        # For music blocks: extract Apple Music link and fetch cover
        cover_html = ''
        if emoji_key == 'yueliang':
            link_m = re.search(r'\[([^\]]+)\]\((https://music\.apple\.com[^)]+)\)', inner)
            if link_m:
                apple_url = link_m.group(2)
                if apple_url not in cover_cache:
                    print(f'    fetching cover for {apple_url[:60]}…')
                    cover_cache[apple_url] = fetch_apple_music_cover(apple_url)
                cover_url = cover_cache.get(apple_url)
                if cover_url:
                    cover_html = f'<img class="music-cover" src="{cover_url}" alt="封面" loading="lazy">'

        inner_html = redoc_inline(inner)
        # convert inner lists
        inner_html = re.sub(r'\n- (.+)', r'<li>\1</li>', inner_html)
        if '<li>' in inner_html:
            inner_html = re.sub(r'(<li>.*</li>)', r'<ul>\1</ul>', inner_html, flags=re.DOTALL)
        inner_html = inner_html.replace('\n\n', '</p><p>').replace('\n', '<br>')

        if cover_html:
            return f'<div class="highlight-block music-block"><div class="music-cover-wrap">{cover_html}</div><div class="hi-body"><span class="hi-emoji">{emoji}</span>{inner_html}</div></div>'
        return f'<div class="highlight-block"><span class="hi-emoji">{emoji}</span><div class="hi-body">{inner_html}</div></div>'

    md = re.sub(r'<redoc-highlight[^>]*>([\s\S]*?)</redoc-highlight>', highlight_block, md)

    lines = md.split('\n')
    html = []
    in_ul = False

    for line in lines:
        # already html block
        if line.strip().startswith('<div class="highlight-block">'):
            if in_ul: html.append('</ul>'); in_ul = False
            html.append(line); continue

        if line.startswith('#### '): 
            if in_ul: html.append('</ul>'); in_ul = False
            html.append(f'<h4>{redoc_inline(line[5:])}</h4>'); continue
        if line.startswith('### '):
            if in_ul: html.append('</ul>'); in_ul = False
            html.append(f'<h3>{redoc_inline(line[4:])}</h3>'); continue
        if line.startswith('## '):
            if in_ul: html.append('</ul>'); in_ul = False
            html.append(f'<h2>{redoc_inline(line[3:])}</h2>'); continue
        if line.startswith('# '):
            if in_ul: html.append('</ul>'); in_ul = False
            html.append(f'<h1>{redoc_inline(line[2:])}</h1>'); continue

        if re.match(r'^---+$', line.strip()):
            if in_ul: html.append('</ul>'); in_ul = False
            html.append('<hr>'); continue

        if line.startswith('- ') or line.startswith('* '):
            if not in_ul: html.append('<ul>'); in_ul = True
            html.append(f'<li>{redoc_inline(line[2:])}</li>'); continue
        else:
            if in_ul: html.append('</ul>'); in_ul = False

        stripped = line.strip()
        if not stripped or stripped == '<br/>': continue
        html.append(f'<p>{redoc_inline(stripped)}</p>')

    if in_ul: html.append('</ul>')
    return '\n'.join(html)


def redoc_inline(text):
    """Inline markdown: links, bold, italic, code."""
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)',
                  r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text


def first_para(content):
    """Extract first real paragraph as excerpt (strip redoc tags)."""
    text = re.sub(r'<font[^>]*>.*?</font>', '', content, flags=re.DOTALL)
    text = re.sub(r'<redoc-highlight[\s\S]*?</redoc-highlight>', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    for para in re.split(r'\n\n+', text.strip()):
        para = para.strip()
        if para and not para.startswith('#') and not re.match(r'^-{3,}$', para):
            return para[:100] + ('…' if len(para) > 100 else '')
    return ''


def build():
    print(f'Fetching index doc {INDEX_DOC_ID}…')
    try:
        index_doc = run_cli(INDEX_DOC_ID)
    except Exception as e:
        print(f'ERROR: {e}')
        sys.exit(1)

    entries_meta = parse_index(index_doc.get('content', ''))
    print(f'Found {len(entries_meta)} entries in index.')

    entries = []
    cover_cache = {}
    for i, meta in enumerate(entries_meta):
        print(f'  [{i+1}/{len(entries_meta)}] {meta["date"]} {meta["title"]}')
        try:
            doc = run_cli(meta['id'])
            content = doc.get('content', '')
            html_body = redoc_md_to_html(content, cover_cache)
            excerpt = first_para(content)
            # weekday
            try:
                dt = datetime.strptime(meta['date'], '%Y-%m-%d')
                wd = WEEKDAY_MAP.get(dt.strftime('%A'), '')
            except:
                wd = ''

            entries.append({
                'id':      meta['id'],
                'date':    meta['date'],
                'weekday': wd,
                'title':   meta['title'],
                'excerpt': excerpt,
                'html':    html_body,
            })
        except Exception as e:
            print(f'    WARNING: failed to fetch {meta["id"]}: {e}')

    os.makedirs(DIST_DIR, exist_ok=True)

    # save raw data JSON
    with open(DATA_PATH, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    print(f'Saved {len(entries)} entries to {DATA_PATH}')

    # write index.html
    html = generate_html(entries)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    # also write to root for GitHub Pages
    root_html = os.path.join(SCRIPT_DIR, 'index.html')
    with open(root_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Written {OUTPUT_PATH} and {root_html}')


def generate_html(entries):
    entries_json = json.dumps(entries, ensure_ascii=False)

    cards_html = ''
    for i, e in enumerate(entries):
        cards_html += f'''    <div class="entry-card" onclick="open_entry({i})">
      <div class="entry-date">{e["date"]} {e["weekday"]}</div>
      <div class="entry-title">{e["title"]}</div>
      <div class="entry-excerpt">{e["excerpt"]}</div>
    </div>\n'''

    template = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>小乐的日记</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📓</text></svg>">
  <link rel="manifest" href="../manifest.json">
  <meta name="theme-color" content="#111111">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="日记">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: 'PingFang SC', 'SF Pro Display', -apple-system, sans-serif;
      background: #fafafa; color: #222; line-height: 1.8;
      -webkit-font-smoothing: antialiased;
    }}
    .container {{ max-width: 640px; margin: 0 auto; padding: 60px 24px 120px; }}

    header {{ margin-bottom: 36px; padding-bottom: 20px; border-bottom: 1px solid #e8e8e8; }}
    header h1 {{ font-size: 18px; font-weight: 500; letter-spacing: 0.5px; color: #111; }}
    header p  {{ font-size: 13px; color: #999; margin-top: 4px; }}

    /* List */
    #view-list {{ display: block; }}
    #view-detail {{ display: none; }}

    .entry-card {{
      background: #fff; border: 1px solid #eee; border-radius: 12px;
      padding: 20px 22px; margin-bottom: 12px; cursor: pointer;
      transition: box-shadow .15s, border-color .15s; text-decoration: none; display: block;
    }}
    .entry-card:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,.07); border-color: #ddd; }}
    .entry-date {{ font-size: 12px; color: #bbb; margin-bottom: 5px; }}
    .entry-title {{ font-size: 16px; font-weight: 600; color: #111; margin-bottom: 7px; line-height: 1.4; }}
    .entry-excerpt {{ font-size: 13px; color: #888; line-height: 1.6; }}

    /* Detail */
    .back-btn {{
      display: inline-flex; align-items: center; gap: 6px;
      font-size: 13px; color: #888; cursor: pointer; margin-bottom: 32px;
      background: none; border: none; padding: 0;
    }}
    .back-btn:hover {{ color: #333; }}
    .detail-meta {{ font-size: 13px; color: #bbb; margin-bottom: 8px; }}
    .detail-title {{ font-size: 22px; font-weight: 700; color: #111; line-height: 1.3; margin-bottom: 28px; }}

    .detail-body {{ font-size: 15px; line-height: 1.9; color: #333; }}
    .detail-body p {{ margin-bottom: 16px; }}
    .detail-body h2 {{ font-size: 16px; font-weight: 600; color: #111; margin: 24px 0 10px; }}
    .detail-body h4 {{ font-size: 15px; font-weight: 600; color: #111; margin: 20px 0 8px; }}
    .detail-body hr {{ border: none; border-top: 1px solid #eee; margin: 24px 0; }}
    .detail-body a {{ color: #0066cc; text-decoration: none; }}
    .detail-body a:hover {{ text-decoration: underline; }}
    .detail-body ul {{ padding-left: 20px; margin-bottom: 16px; }}
    .detail-body li {{ margin-bottom: 6px; }}
    .detail-body .entry-meta {{ color: #bbb; font-size: 13px; }}

    /* Highlight blocks (音乐 / 延伸阅读) */
    .highlight-block {{
      background: #f5f5f5; border-radius: 10px; padding: 16px 18px;
      margin: 20px 0; display: flex; gap: 12px; align-items: flex-start;
    }}
    .hi-emoji {{ font-size: 18px; flex-shrink: 0; margin-top: 2px; }}
    .hi-body {{ font-size: 14px; flex: 1; }}
    .hi-body strong {{ font-size: 13px; color: #888; display: block; margin-bottom: 8px; }}
    .hi-body a {{ color: #0066cc; text-decoration: none; }}
    .hi-body a:hover {{ text-decoration: underline; }}
    .hi-body ul {{ padding-left: 16px; margin-top: 6px; }}
    .hi-body li {{ margin-bottom: 4px; }}

    /* Music cover */
    .music-block {{ align-items: flex-start; gap: 14px; }}
    .music-cover-wrap {{ flex-shrink: 0; }}
    .music-cover {{
      width: 80px; height: 80px; border-radius: 8px;
      object-fit: cover; display: block;
      box-shadow: 0 2px 8px rgba(0,0,0,.12);
    }}
    .music-block .hi-body {{ padding-top: 2px; }}

    .updated-note {{ font-size: 12px; color: #ccc; text-align: right; margin-top: 40px; }}
  </style>
</head>
<body>
<div class="container">
  <header>
    <h1>📓 小乐的日记</h1>
    <p id="header-sub">ENTRY_COUNT 篇</p>
  </header>

  <div id="view-list">
    ENTRY_CARDS_PLACEHOLDER
  </div>

  <div id="view-detail">
    <button class="back-btn" onclick="show_list()">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
      返回
    </button>
    <div class="detail-meta" id="d-meta"></div>
    <div class="detail-title" id="d-title"></div>
    <div class="detail-body" id="d-body"></div>
    <div class="updated-note" id="d-note"></div>
  </div>
</div>

<script>
const ENTRIES = {entries_json};

function open_entry(i) {{
  const e = ENTRIES[i];
  document.getElementById('view-list').style.display = 'none';
  document.getElementById('view-detail').style.display = 'block';
  document.getElementById('d-meta').textContent = e.date + (e.weekday ? ' · ' + e.weekday : '');
  document.getElementById('d-title').textContent = e.title;
  document.getElementById('d-body').innerHTML = e.html;
  document.title = e.title + ' · 小乐的日记';
  history.pushState({{i}}, '', '#' + i);
  window.scrollTo(0, 0);
}}

function show_list() {{
  document.getElementById('view-detail').style.display = 'none';
  document.getElementById('view-list').style.display = 'block';
  document.title = '小乐的日记';
  history.pushState({{}}, '', location.pathname);
  window.scrollTo(0, 0);
}}

window.addEventListener('popstate', e => {{
  if (e.state && e.state.i !== undefined) open_entry(e.state.i);
  else show_list();
}});

// handle direct hash link
const hash = location.hash.slice(1);
if (hash && !isNaN(parseInt(hash))) open_entry(parseInt(hash));
</script>
</body>
</html>'''

    template = template.replace('ENTRY_CARDS_PLACEHOLDER', cards_html)
    template = template.replace('ENTRY_COUNT', str(len(entries)))
    return template


if __name__ == '__main__':
    build()
