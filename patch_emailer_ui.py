import re

with open("app/utils/email_templates.py", "r") as f:
    content = f.read()

# 1. Replace "Here's your<br />security code" with "Your security<br />code"
content = content.replace("Here's your<br />security code", "Your security<br />code")

# 2. Add clock icon to the expires text
clock_icon = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#5E6D65" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;margin-bottom:2px;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>"""
content = content.replace("This code will expire in", f"{clock_icon} Expires in")

# 3. Replace shield_graphic
new_shield = """
    shield_graphic = '''
    <div style="text-align: center; position: relative;">
        <!-- Using a robust SVG for the entire illustration to avoid email client CSS issues -->
        <svg width="220" height="240" viewBox="0 0 220 240" fill="none" xmlns="http://www.w3.org/2000/svg">
            <!-- Light green blob -->
            <path d="M185.3 47.7C208.7 75.3 219.7 114.9 211.2 147.2C202.7 179.5 174.6 204.6 142.1 217.4C109.6 230.2 72.8 230.6 44.9 214.3C17 198  -1.9 164.9 0.1 133.3C2.1 101.6 15 71.4 36.9 45.4C58.8 19.4 89.8 -2.4 122 -0.8C154.2 0.8 161.9 20.1 185.3 47.7Z" fill="#F1F5E8" />
            
            <!-- Lime green rays -->
            <path d="M63 67 L53 62" stroke="#C3EC30" stroke-width="4" stroke-linecap="round" />
            <path d="M50 90 L40 93" stroke="#C3EC30" stroke-width="4" stroke-linecap="round" />
            <path d="M56 114 L49 123" stroke="#C3EC30" stroke-width="4" stroke-linecap="round" />
            
            <path d="M157 51 L163 42" stroke="#C3EC30" stroke-width="4" stroke-linecap="round" />
            <path d="M174 65 L184 62" stroke="#C3EC30" stroke-width="4" stroke-linecap="round" />
            
            <!-- Shield -->
            <path d="M110 50L75 62.5V106.25C75 142.875 89.875 176.625 110 190C130.125 176.625 145 142.875 145 106.25V62.5L110 50Z" fill="#D3E6D8" />
            
            <!-- Padlock inside shield -->
            <!-- Lock body -->
            <rect x="95" y="105" width="30" height="22" rx="4" fill="#0C2E20" />
            <!-- Lock shackle -->
            <path d="M100 105V95C100 89.4772 104.477 85 110 85C115.523 85 120 89.4772 120 95V105" stroke="#0C2E20" stroke-width="4" stroke-linecap="round" />
            <!-- Lock keyhole -->
            <circle cx="110" cy="116" r="3" fill="#D3E6D8" />
            <path d="M109 118H111V123H109V118Z" fill="#D3E6D8" />
        </svg>
        <div style="margin-top:-30px; margin-left: 50px; font-family: 'Caveat', 'Comic Sans MS', cursive; font-size: 18px; color:#1F6C4C; transform: rotate(-10deg);">
            You're<br>in safe hands
        </div>
    </div>
    '''
"""
content = re.sub(r"    shield_graphic = '''[\s\S]*?    '''", new_shield.strip(), content)

with open("app/utils/email_templates.py", "w") as f:
    f.write(content)
