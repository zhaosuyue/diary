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
    # lookup by id — works for both albums and songs (tracks)
    api_url = f'https://itunes.apple.com/lookup?id={item_id}&country=cn'
    try:
        with urllib.request.urlopen(api_url, timeout=8) as r:
            data = json.loads(r.read())
        results = data.get('results', [])
        for item in results:
            art = item.get('artworkUrl100', '')
            if art:
                return art.replace('100x100bb', '600x600bb')
    except:
        pass
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
            return f'<div class="hi-block music-block"><div class="music-cover-wrap">{cover_html}</div><div class="hi-content"><span class="hi-icon">{emoji}</span>{inner_html}</div></div>'
        return f'<div class="hi-block"><span class="hi-icon">{emoji}</span><div class="hi-content">{inner_html}</div></div>'

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
        cards_html += (
            f'<div class="card" onclick="open_entry({i})">'
            f'<div class="card-date">{e["date"]} {e["weekday"]}</div>'
            f'<div class="card-title">{e["title"]}</div>'
            f'<div class="card-excerpt">{e["excerpt"]}</div>'
            f'</div>\n'
        )

    css = """
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :root {
      --bg:       #f6f6f4;
      --surface:  #ffffff;
      --border:   #e8e8e6;
      --text1:    #111111;
      --text2:    #444444;
      --text3:    #888888;
      --text4:    #bbbbbb;
      --accent:   #0055cc;
      --hi-bg:    #f0f0ee;
      --shadow:   0 1px 4px rgba(0,0,0,.06);
      --r:        10px;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg:      #161618;
        --surface: #1e1e21;
        --border:  #2a2a2e;
        --text1:   #e8e8e8;
        --text2:   #aaaaaa;
        --text3:   #666666;
        --text4:   #444444;
        --accent:  #4d9fff;
        --hi-bg:   #242428;
        --shadow:  0 1px 6px rgba(0,0,0,.25);
      }
    }

    body {
      font-family: -apple-system, 'PingFang SC', 'SF Pro Text', sans-serif;
      background: var(--bg);
      color: var(--text1);
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
      font-size: 15px;
    }

    .wrap { max-width: 520px; margin: 0 auto; padding: 48px 20px 80px; }

    /* ── Header ── */
    .site-header { margin-bottom: 28px; }
    .site-title { font-size: 16px; font-weight: 600; color: var(--text1); }
    .site-count { font-size: 12px; color: var(--text3); margin-top: 2px; }

    /* ── List ── */
    #view-list  { display: block; }
    #view-detail { display: none; }

    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r);
      padding: 16px 18px;
      margin-bottom: 8px;
      cursor: pointer;
      transition: box-shadow .12s;
    }
    .card:hover { box-shadow: var(--shadow); }
    .card-date  { font-size: 11px; color: var(--text4); margin-bottom: 4px; letter-spacing: .3px; }
    .card-title { font-size: 14px; font-weight: 600; color: var(--text1); margin-bottom: 5px; line-height: 1.4; }
    .card-excerpt { font-size: 13px; color: var(--text3); line-height: 1.5; }

    /* ── Detail ── */
    .back {
      display: inline-flex; align-items: center; gap: 5px;
      font-size: 13px; color: var(--text3); background: none;
      border: none; cursor: pointer; margin-bottom: 24px; padding: 0;
    }
    .back:hover { color: var(--text1); }
    .back svg { width: 14px; height: 14px; }

    .d-date  { font-size: 11px; color: var(--text4); letter-spacing: .3px; margin-bottom: 6px; }
    .d-title { font-size: 19px; font-weight: 700; line-height: 1.3; color: var(--text1); margin-bottom: 22px; }

    .d-body { font-size: 14px; line-height: 1.7; color: var(--text2); }
    .d-body p  { margin-bottom: 10px; }
    .d-body h4 { font-size: 13px; font-weight: 600; color: var(--text1);
                 margin: 18px 0 6px; letter-spacing: .2px; }
    .d-body hr { border: none; border-top: 1px solid var(--border); margin: 18px 0; }
    .d-body a  { color: var(--accent); text-decoration: none; }
    .d-body a:hover { text-decoration: underline; }
    .d-body ul { padding-left: 16px; margin-bottom: 10px; }
    .d-body li { margin-bottom: 3px; }
    .d-body .entry-meta { display: none; }

    /* ── Highlight block ── */
    .hi-block {
      background: var(--hi-bg);
      border-radius: 8px;
      padding: 12px 14px;
      margin: 14px 0;
      display: flex;
      gap: 10px;
      align-items: flex-start;
    }
    .hi-icon { font-size: 14px; flex-shrink: 0; line-height: 1.7; }
    .hi-content { font-size: 13px; color: var(--text2); line-height: 1.55; flex: 1; }
    .hi-content strong {
      display: block; font-size: 11px; font-weight: 600; color: var(--text3);
      text-transform: uppercase; letter-spacing: .6px; margin-bottom: 6px;
    }
    .hi-content a  { color: var(--accent); text-decoration: none; }
    .hi-content a:hover { text-decoration: underline; }
    .hi-content ul { padding-left: 14px; margin-top: 4px; }
    .hi-content li { margin-bottom: 3px; }

    /* ── Music block (with cover) ── */
    .music-block { padding: 10px 12px; }
    .music-cover-wrap { flex-shrink: 0; }
    .music-cover {
      width: 64px; height: 64px;
      border-radius: 6px;
      object-fit: cover;
      display: block;
    }
    .music-block .hi-icon { display: none; }
    .music-block .hi-content { padding-top: 1px; }
    """

    js = f"""
const ENTRIES = {entries_json};

function open_entry(i) {{
  const e = ENTRIES[i];
  document.getElementById('view-list').style.display = 'none';
  document.getElementById('view-detail').style.display = 'block';
  document.querySelector('.d-date').textContent = e.date + (e.weekday ? '  ' + e.weekday : '');
  document.querySelector('.d-title').textContent = e.title;
  document.querySelector('.d-body').innerHTML = e.html;
  document.title = e.title + ' · 日记';
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

window.addEventListener('popstate', ev => {{
  if (ev.state && ev.state.i !== undefined) open_entry(ev.state.i);
  else show_list();
}});

const h = location.hash.slice(1);
if (h && !isNaN(+h)) open_entry(+h);
"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>小乐的日记</title>
<meta name="theme-color" content="#f6f6f4" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161618" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="日记">
<style>{css}</style>
</head>
<body>
<div class="wrap">

  <header class="site-header">
    <div class="site-title">📓 小乐的日记</div>
    <div class="site-count">{len(entries)} 篇</div>
  </header>

  <div id="view-list">
{cards_html}  </div>

  <div id="view-detail">
    <button class="back" onclick="show_list()">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      返回
    </button>
    <div class="d-date"></div>
    <div class="d-title"></div>
    <div class="d-body"></div>
  </div>

</div>
<script>{js}</script>
</body>
</html>"""


if __name__ == '__main__':
    build()
