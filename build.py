#!/usr/bin/env python3
"""Build diary site from markdown entries — list + detail SPA."""
import os, re, glob, json
from datetime import datetime

ENTRIES_DIR   = os.path.join(os.path.dirname(__file__), 'entries')
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'index.html')
OUTPUT_PATH   = os.path.join(os.path.dirname(__file__), 'dist', 'index.html')


def parse_reading_block(text):
    """Extract <!-- reading ... --> block, return (cleaned_text, list of (title, source, url))."""
    pattern = r'<!--\s*reading\s*(.*?)-->'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text, []
    raw = match.group(1).strip()
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split('|')]
        if len(parts) == 3:
            items.append({'title': parts[0], 'source': parts[1], 'url': parts[2]})
        elif len(parts) == 2:
            items.append({'title': parts[0], 'source': '', 'url': parts[1]})
    cleaned = text[:match.start()].rstrip() + text[match.end():]
    return cleaned, items


def reading_block_html(items):
    """Render further reading section."""
    if not items:
        return ''
    links_html = ''
    for item in items:
        source_html = f'<span class="reading-source"> — {item["source"]}</span>' if item['source'] else ''
        links_html += f'<a class="reading-link" href="{item["url"]}" target="_blank" rel="noopener">{item["title"]}{source_html}</a>\n'
    return f'''<div class="reading-section">
  <div class="reading-label">延伸阅读</div>
  {links_html}</div>'''


def parse_music_block(text):
    """Extract <!-- music ... --> block and return (cleaned_text, music_dict|None)."""
    pattern = r'<!--\s*music\s*(.*?)-->'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return text, None
    raw = match.group(1).strip()
    music = {}
    for line in raw.splitlines():
        if ':' in line:
            key, _, val = line.partition(':')
            music[key.strip()] = val.strip()
    cleaned = text[:match.start()].rstrip() + text[match.end():]
    return cleaned, music if music else None


def md_to_html(text):
    """Minimal markdown → HTML (paragraphs, bold, italic, hr)."""
    text = text.strip()
    blocks = re.split(r'\n\n+', text)
    html_parts = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block == '---':
            html_parts.append('<hr>')
            continue
        block = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', block)
        block = re.sub(r'\*(.+?)\*',     r'<em>\1</em>', block)
        block = block.replace('\n', ' ')
        html_parts.append(f'<p>{block}</p>')
    return '\n'.join(html_parts)


def music_card_html(music):
    """Render a clickable Apple Music card."""
    title  = music.get('title', '')
    artist = music.get('artist', '')
    cover  = music.get('cover', '')
    url    = music.get('apple_music', '#')
    note   = music.get('note', '')

    # Apple Music cover: use itunes API thumbnail format as fallback
    cover_html = f'<img class="music-cover" src="{cover}" alt="{title}" onerror="this.style.background=\'#e8e8e8\';this.style.display=\'block\'">' if cover else '<div class="music-cover music-cover-placeholder"></div>'

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
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
  </div>
</a>'''


def first_sentence(text, max_chars=80):
    text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*+', '', text)
    for para in re.split(r'\n\n+', text.strip()):
        para = para.strip()
        if para and para != '---':
            return para[:max_chars] + ('…' if len(para) > max_chars else '')
    return ''


def parse_entry(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.strip().split('\n')
    title, body_lines = '', lines
    if lines and lines[0].startswith('# '):
        title = lines[0][2:].strip()
        body_lines = lines[1:]

    filename = os.path.basename(filepath)
    date_str = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
    date_str = date_str.group(1) if date_str else datetime.now().strftime('%Y-%m-%d')
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    display  = date_obj.strftime('%Y.%m.%d')

    body_md = '\n'.join(body_lines).strip()
    body_md, reading = parse_reading_block(body_md)
    body_md, music = parse_music_block(body_md)
    body_html = md_to_html(body_md)

    if music:
        body_html += '\n' + music_card_html(music)
    if reading:
        body_html += '\n' + reading_block_html(reading)

    summary = first_sentence(body_md)

    return {
        'id':       date_str,
        'date':     display,
        'date_obj': date_obj,
        'title':    title,
        'summary':  summary,
        'body':     body_html,
    }


def build():
    files   = glob.glob(os.path.join(ENTRIES_DIR, '*.md'))
    entries = []
    for f in files:
        try:
            entries.append(parse_entry(f))
        except Exception as e:
            print(f'Error parsing {f}: {e}')

    entries.sort(key=lambda e: e['date_obj'], reverse=True)

    list_html = ''
    for e in entries:
        list_html += f'''
      <a class="entry-card" onclick="showDetail('{e['id']}'); return false;" href="#{e['id']}">
        <div class="entry-date">{e['date']}</div>
        <div class="entry-title">{e['title']}</div>
        <div class="entry-summary">{e['summary']}</div>
      </a>'''

    entries_dict = {e['id']: {'date': e['date'], 'title': e['title'], 'body': e['body']} for e in entries}
    entries_json = json.dumps(entries_dict, ensure_ascii=False)

    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        template = f.read()

    output = template.replace('{{list_html}}', list_html)
    output = output.replace('{{entries_json}}', entries_json)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(output)

    print(f'Built {len(entries)} entries → {OUTPUT_PATH}')


if __name__ == '__main__':
    build()
