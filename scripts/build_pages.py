import markdown, os, html

report_dir = 'reports'
site_dir = '_site'
nav_links = []

if os.path.isdir(report_dir):
    for f in sorted(os.listdir(report_dir)):
        if not f.endswith('.md'):
            continue
        md_path = os.path.join(report_dir, f)
        with open(md_path, 'r', encoding='utf-8') as fp:
            body = markdown.markdown(fp.read(), extensions=['fenced_code', 'tables'])
        name = f.rsplit('.', 1)[0]
        html_path = os.path.join(site_dir, f.replace('.md', '.html'))
        with open(html_path, 'w', encoding='utf-8') as fp:
            fp.write(f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(name)} - 每日股票分析</title><style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:960px;margin:0 auto;padding:20px;line-height:1.7;color:#333}}h1{{border-bottom:2px solid #eee;padding-bottom:8px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background:#f5f5f5}}code{{background:#f0f0f0;padding:2px 6px;border-radius:3px}}pre code{{display:block;overflow-x:auto;padding:12px}}a{{color:#0366d6}}</style></head><body>{body}</body></html>''')
        nav_links.append(f'<a href="{html.escape(f.replace(".md", ".html"))}">{html.escape(name)}</a>')

if nav_links:
    items = '<br>'.join(nav_links)
    index_html = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>每日股票分析 - 报告列表</title><style>body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:720px;margin:0 auto;padding:40px 20px;line-height:2}}a{{display:block;font-size:18px;color:#0366d6}}a:hover{{text-decoration:underline}}h1{{border-bottom:2px solid #eee;padding-bottom:10px}}</style></head><body><h1>每日股票分析报告</h1>{items}</body></html>'''
    with open(os.path.join(site_dir, 'index.html'), 'w', encoding='utf-8') as fp:
        fp.write(index_html)
    print(f'生成 {len(nav_links)} 个报告页面 + index.html')
else:
    with open(os.path.join(site_dir, 'index.html'), 'w', encoding='utf-8') as fp:
        fp.write('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>每日股票分析</title></head><body><p>暂无报告</p></body></html>')
    print('无报告文件，生成占位 index.html')
