#!/usr/bin/env python3
"""Build diary site from markdown entries — list + detail SPA."""
import os, re, glob, json
from datetime import datetime

ENTRIES_DIR   = os.path.join(os.path.dirname(__file__), 'entries')
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'index.html')
OUTPUT_PATH   = os.path.join(os.path.dirname(__file__), 'dist', 'index.html')


# ── Block parsers ──────────────────────────────────────────────────────────────

def strip_block(text, kind):
    """Remove <!-- kind ... --> from text, return (cleaned, raw_content|None)."""
    pattern = rf'<!--\s*{kind}\s*(.*?)-->'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text, None
    cleaned = (text[:match.start()] + text[match.end():]).strip()
    return cleaned, match.group(1).strip()


def parse_kv_block(raw):
    """Parse key: value lines into dict."""
    d = {}
    for line in raw.splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            d[k.strip()] = v.strip()
    return d


def parse_tags(text):
    """Extract 'tags: a, b, c' line from top of body, return (cleaned, [tags])."""
    match = re.match(r'^tags:\s*(.+)$', text.strip(), re.MULTILINE)
    if not match:
        return text, []
    tags = [t.strip() for t in match.group(1).split(',') if t.strip()]
    cleaned = text.replace(match.group(0), '').strip()
    return cleaned, tags


# ── HTML renderers ─────────────────────────────────────────────────────────────

def article_card_html(music):
    title  = music.get('title', '')
    source = music.get('source', '')
    url    = music.get('url', '#')
    source_html = f'<div class="article-source">{source}</div>' if source else ''
    return f'''<a class="article-card" href="{url}" target="_blank" rel="noopener">
  <div class="article-info">
    <div class="article-label">来自文章</div>
    <div class="article-title">{title}</div>
    {source_html}
  </div>
  <div class="music-arrow">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
  </div>
</a>'''


def music_card_html(music):
    title  = music.get('title', '')
    artist = music.get('artist', '')
    cover  = music.get('cover', '')
    url    = music.get('apple_music', '#')
    note   = music.get('note', '')
    cover_html = f'<img class="music-cover" src="{cover}" alt="{title}" onerror="this.style.background=\'#e8e8e8\'">' if cover else '<div class="music-cover music-cover-placeholder"></div>'
    note_html = f'<div class="music-note">{note}</div>' if note else ''
    return f'''<a class="music-card" href="{url}" target="_blank" rel="noopener">
  {cover_html}
  <div class="music-info">
    <div class="music-label">今天在听</div>
    <div class="music-title">{title}</div>
    <div class="music-artist">{artist}</div>
    {note_html}
  </div>
  <div class="music-arrow">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
  </div>
</a>'''


def reading_block_html(items):
    if not items:
        return ''
    links = ''
    for item in items:
        src = f'<span class="reading-source"> — {item["source"]}</span>' if item.get('source') else ''
        links += f'<a class="reading-link" href="{item["url"]}" target="_blank" rel="noopener">{item["title"]}{src}</a>\n'
    return f'<div class="reading-section"><div class="reading-label">延伸阅读</div>{links}</div>'


def md_to_html(text):
    """Minimal markdown → HTML (h2, paragraphs, bold, italic, hr)."""
    text = text.strip()
    # Split on blank lines, but keep article blocks inline
    # First, extract article blocks and replace with placeholders
    article_placeholders = {}
    def replace_article(m):
        key = f'__ARTICLE_{len(article_placeholders)}__'
        raw = m.group(1).strip()
        article_placeholders[key] = article_card_html(parse_kv_block(raw))
        return f'\n\n{key}\n\n'
    text = re.sub(r'<!--\s*article\s*(.*?)-->', replace_article, text, flags=re.DOTALL)

    blocks = re.split(r'\n\n+', text)
    html_parts = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block in article_placeholders:
            html_parts.append(article_placeholders[block])
            continue
        if block == '---':
            html_parts.append('<hr>')
            continue
        if block.startswith('## '):
            html_parts.append(f'<h2 class="entry-section-title">{block[3:].strip()}</h2>')
            continue
        block = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', block)
        block = re.sub(r'\*(.+?)\*',     r'<em>\1</em>', block)
        block = block.replace('\n', ' ')
        html_parts.append(f'<p>{block}</p>')
    return '\n'.join(html_parts)


def first_sentence(text, max_chars=80):
    """Fallback: grab first real paragraph."""
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'^tags:.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*+', '', text)
    for para in re.split(r'\n\n+', text.strip()):
        para = para.strip()
        if para and para != '---' and not para.startswith('##'):
            return para[:max_chars] + ('…' if len(para) > max_chars else '')
    return ''


def extract_summary(text):
    """Extract hand-written summary from 'summary: ...' line, or fall back."""
    match = re.match(r'^summary:\s*(.+)$', text.strip(), re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


# ── Entry parser ───────────────────────────────────────────────────────────────

def parse_entry(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Strip YAML front matter if present
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if fm_match:
        fm_raw = fm_match.group(1)
        body_lines = content[fm_match.end():].split('\n')
        # Extract title/date/tags from front matter as fallback
        fm = parse_kv_block(fm_raw)
        fm_title = fm.get('title', '').strip('"\'')
        fm_tags_raw = fm.get('tags', '')
        # Handle YAML array syntax: [tag1, tag2]
        fm_tags = []
        arr_match = re.match(r'\[(.+)\]', fm_tags_raw)
        if arr_match:
            fm_tags = [t.strip().strip('"\'') for t in arr_match.group(1).split(',')]
    else:
        fm_title = ''
        fm_tags = []
        lines = content.strip().split('\n')
        body_lines = lines

    title = fm_title
    if not title and body_lines and body_lines[0].startswith('# '):
        title = body_lines[0][2:].strip()
        body_lines = body_lines[1:]

    filename = os.path.basename(filepath)
    date_str = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
    date_str = date_str.group(1) if date_str else datetime.now().strftime('%Y-%m-%d')
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    display  = date_obj.strftime('%Y.%m.%d')

    body_md = '\n'.join(body_lines).strip()

    # Extract summary line
    summary_override = extract_summary(body_md)
    if summary_override:
        body_md = re.sub(r'^summary:.*$', '', body_md, flags=re.MULTILINE).strip()

    # Extract tags from body; fall back to front matter tags
    body_md, tags = parse_tags(body_md)
    if not tags:
        tags = fm_tags

    # Extract reading block (always at end)
    body_md, reading_raw = strip_block(body_md, 'reading')
    reading_items = []
    if reading_raw:
        for line in reading_raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) == 3:
                reading_items.append({'title': parts[0], 'source': parts[1], 'url': parts[2]})
            elif len(parts) == 2:
                reading_items.append({'title': parts[0], 'source': '', 'url': parts[1]})

    # Extract music block (always at end)
    body_md, music_raw = strip_block(body_md, 'music')
    music = parse_kv_block(music_raw) if music_raw else None

    # article blocks stay inline — handled inside md_to_html
    # Make body HTML single-line to avoid issues when embedding in <script>
    body_html = md_to_html(body_md).replace('\n', ' ').replace('\r', '')
    if music:
        body_html += '\n' + music_card_html(music)
    if reading_items:
        body_html += '\n' + reading_block_html(reading_items)

    summary = summary_override if summary_override else first_sentence(body_md)

    return {
        'id':       date_str,
        'date':     display,
        'date_obj': date_obj,
        'title':    title,
        'tags':     tags,
        'summary':  summary,
        'body':     body_html,
    }


# ── Build ──────────────────────────────────────────────────────────────────────

def build():
    files   = glob.glob(os.path.join(ENTRIES_DIR, '*.md'))
    entries = []
    for f in files:
        try:
            entries.append(parse_entry(f))
        except Exception as e:
            print(f'Error parsing {f}: {e}')

    entries.sort(key=lambda e: e['date_obj'], reverse=True)

    # Collect all tags
    all_tags = []
    for e in entries:
        for t in e['tags']:
            if t not in all_tags:
                all_tags.append(t)

    # List HTML
    list_html = ''
    for e in entries:
        tags_attr = ','.join(e['tags'])
        tags_html = ''.join(f'<span class="entry-tag">{t}</span>' for t in e['tags'])
        list_html += f'''
      <a class="entry-card" data-tags="{tags_attr}" onclick="showDetail('{e['id']}'); return false;" href="#{e['id']}">
        <div class="entry-date">{e['date']}{tags_html}</div>
        <div class="entry-title">{e['title']}</div>
        <div class="entry-summary">{e['summary']}</div>
      </a>'''

    # Tab HTML
    tabs_html = '<button class="tab active" onclick="filterTag(\'全部\', this)">全部</button>\n'
    for t in all_tags:
        tabs_html += f'<button class="tab" onclick="filterTag(\'{t}\', this)">{t}</button>\n'

    entries_dict = {e['id']: {'date': e['date'], 'title': e['title'], 'body': e['body'], 'tags': e['tags']} for e in entries}
    entries_json = json.dumps(entries_dict, ensure_ascii=False)

    # Read the current built HTML as base template
    # Try dist/index.html first, then root index.html
    base_paths = [OUTPUT_PATH, TEMPLATE_PATH]
    template = None
    for p in base_paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                template = f.read()
            break
    if template is None:
        print('Error: no base HTML found')
        return

    # Replace entries JSON: const entries = {...};
    json_pattern = r'(const entries\s*=\s*)\{.*?\};'
    template = re.sub(json_pattern, r'\g<1>' + entries_json + ';', template, flags=re.DOTALL)

    # Replace tabs section: <div class="tabs">...</div>
    tabs_pattern = r'(<div class="tabs">\s*)[\s\S]*?(</div>)'
    # Find the tabs div, replace content between it and the matching </div>
    tabs_start_marker = '<div class="tabs">'
    tabs_idx = template.find(tabs_start_marker)
    if tabs_idx >= 0:
        # Find the closing </div> that matches the tabs div
        inner_start = tabs_idx + len(tabs_start_marker)
        # Count from the first </div> after tabs_start
        # The tabs div contains only button elements, so the first </div> after tabs_start closes it
        search_start = inner_start
        while True:
            close_idx = template.find('</div>', search_start)
            if close_idx < 0:
                break
            # Check there's no nested div between inner_start and close_idx
            between = template[inner_start:close_idx]
            open_count = between.count('<div')
            close_count = between.count('</div>')
            if open_count == close_count:
                # This is the matching close tag
                template = template[:inner_start] + '\n' + tabs_html + '    ' + template[close_idx:]
                break
            search_start = close_idx + 6

    # Replace list section: entry cards between tabs and <script>
    script_idx = template.find('<script>')
    if script_idx >= 0:
        # Find the first entry-card after the tabs div
        first_card = template.find('<a class="entry-card"', tabs_idx)
        if first_card >= 0 and first_card < script_idx:
            # Find the end of the last entry-card before <script>
            # Look backwards from script_idx for the last </a>
            last_card_end = template.rfind('</a>', first_card, script_idx)
            if last_card_end >= 0:
                template = template[:first_card] + list_html + '\n    ' + template[last_card_end + 4:]

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(template)

    # Also update root index.html
    with open(TEMPLATE_PATH, 'w', encoding='utf-8') as f:
        f.write(template)

    print(f'Built {len(entries)} entries → {OUTPUT_PATH}')


if __name__ == '__main__':
    build()
