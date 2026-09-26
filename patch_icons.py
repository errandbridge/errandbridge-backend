from __future__ import annotations
import re

with open("app/utils/email_templates.py", "r") as f:
    content = f.read()

# Better icons (Solid + styled)
icon_cart = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path></svg>'''
icon_map = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"></polygon><line x1="9" y1="3" x2="9" y2="18"></line><line x1="15" y1="6" x2="15" y2="21"></line></svg>'''
icon_users = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'''
icon_shield = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>'''

content = re.sub(r"icon_cart = '''<svg.*?'''", f"icon_cart = '''{icon_cart}'''", content, flags=re.DOTALL)
content = re.sub(r"icon_map = '''<svg.*?'''", f"icon_map = '''{icon_map}'''", content, flags=re.DOTALL)
content = re.sub(r"icon_users = '''<svg.*?'''", f"icon_users = '''{icon_users}'''", content, flags=re.DOTALL)
content = re.sub(r"icon_shield = '''<svg.*?'''", f"icon_shield = '''{icon_shield}'''", content, flags=re.DOTALL)

with open("app/utils/email_templates.py", "w") as f:
    f.write(content)
