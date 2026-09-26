from __future__ import annotations
import re

with open("app/utils/email_templates.py", "r") as f:
    content = f.read()

# Make the feature icons background white and add dividers
# old: <td style="padding:30px 20px;background-color:#FAFCF8;border-top:1px solid {colors['line']};">
# new: <td style="padding:30px 20px;background-color:#FFFFFF;border-top:1px solid {colors['line']};">
content = content.replace(
    """<td style="padding:30px 20px;background-color:#FAFCF8;border-top:1px solid {colors['line']};">""",
    """<td style="padding:30px 20px;background-color:#FFFFFF;border-top:1px solid {colors['line']};">"""
)

# Add right borders to the first 3 feature cells
content = content.replace(
    """<td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;">""",
    """<td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;border-right:1px solid {colors['line']};">""", 
    3 # Replace the first 3
)

# Social icons
svg_x = """<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>"""
svg_insta = """<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>"""
svg_fb = """<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"></path></svg>"""
svg_in = """<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"></path><rect x="2" y="9" width="4" height="12"></rect><circle cx="4" cy="4" r="2"></circle></svg>"""
svg_yt = """<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"></path><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"></polygon></svg>"""

social_html = f"""          <div style="margin-top:20px;font-size:16px;color:#A4B2AA;letter-spacing:10px;">
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;">{svg_x}</a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;">{svg_insta}</a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;">{svg_fb}</a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;">{svg_in}</a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;">{svg_yt}</a>
          </div>"""

content = re.sub(r"          <div style=\"margin-top:20px;font-size:16px;color:#A4B2AA;letter-spacing:10px;\">.*?</div>", social_html, content, flags=re.DOTALL)

with open("app/utils/email_templates.py", "w") as f:
    f.write(content)
