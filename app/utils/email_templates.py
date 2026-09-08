
def get_security_code_email(code: str, expires_in_minutes: int = 10) -> str:
    # 60:30:10 rule inspired colors
    colors = {
        "paper": "#F8FAED",
        "white": "#FFFFFF",
        "brand": "#1F6C4C",
        "brandDeep": "#0C2E20",
        "sage": "#F1F5E8",
        "sageDeep": "#E4E9D8",
        "lime": "#C3EC30",
        "muted": "#7C8D84",
        "line": "#E5EBE5",
        "cardBg": "#FFFFFF",
        "buttonBg": "#F0F5E9",
        "buttonText": "#1F6C4C"
    }

    # Format the code digits into styled cells
    digits = list(code.replace(" ", ""))
    digit_cells = "".join([
        f'''
        <td width="52" align="center">
          <div style="height:52px;line-height:52px;font-size:24px;font-weight:700;color:{colors['brandDeep']};background-color:{colors['white']};border:1px solid {colors['sageDeep']};border-radius:6px;">
            {digit}
          </div>
        </td>
        ''' for digit in digits
    ])

    # Logo Mark URL
    logo_full_url = "https://errandbridge.com/logo-full.png"
    logo_mark_url = "https://errandbridge.com/logo-mark.png"

    # Outline SVGs for the footer
    icon_cart = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path></svg>'''
    icon_map = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"></polygon><line x1="9" y1="3" x2="9" y2="18"></line><line x1="15" y1="6" x2="15" y2="21"></line></svg>'''
    icon_users = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'''
    icon_shield = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>'''

    # Shield graphic SVGs for the right side
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

    return f'''
<div style="background-color:{colors['paper']};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;padding:30px 10px;min-height:100vh;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="max-width:680px;margin:0 auto;width:100%;">
    <tbody>
      <tr>
        <td style="padding:0 8px 18px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
            <tbody>
              <tr>
                <td style="vertical-align:middle;">
                  <img src="{logo_full_url}" alt="ErrandBridge" height="32" style="display:block;border:0;height:32px;" onerror="this.outerHTML='<div style=\'font-size:24px;font-weight:800;color:{colors['brandDeep']};\'>ErrandBridge</div>'" />
                </td>
                <td style="text-align:right;color:{colors['muted']};font-size:14px;line-height:1.5;vertical-align:middle;">
                  Everyday tasks, easier together.
                </td>
              </tr>
            </tbody>
          </table>
        </td>
      </tr>

      <tr>
        <td>
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;background-color:{colors['white']};border-radius:14px;overflow:hidden;box-shadow:0 8px 24px rgba(13, 74, 53, 0.05);">
            <tbody>
              <tr>
                <td style="padding:40px;">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tr>
                      <td style="vertical-align:top; width: 60%;">
                        <p style="margin:0;color:{colors['muted']};font-size:12px;font-weight:800;letter-spacing:3px;text-transform:uppercase;">Security code</p>
                        <h1 style="margin:12px 0 10px;color:{colors['brandDeep']};font-size:38px;line-height:1.1;font-weight:800;letter-spacing:-1px;">
                          Your security<br />code
                        </h1>
                        <p style="margin:0;color:#56655E;font-size:16px;line-height:1.6;max-width:300px;">
                          Use the code below to continue signing in to your ErrandBridge account.
                        </p>
                        <div style="margin-top:30px;padding:24px 20px;border-radius:12px;background-color:{colors['sage']};display:inline-block;">
                          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;border-spacing:6px 0;">
                            <tbody>
                              <tr>
                                {digit_cells}
                              </tr>
                            </tbody>
                          </table>
                          <p style="margin:16px 0 0;text-align:center;color:#5E6D65;font-size:13px;line-height:1.5;">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#5E6D65" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;margin-bottom:2px;"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> Expires in <strong style="color:{colors['brandDeep']};">{expires_in_minutes} minutes</strong>.
                          </p>
                        </div>
                      </td>
                      <td style="vertical-align:middle; text-align:center; width: 40%; display:none; display:table-cell\9;" class="hide-on-mobile">
                        {shield_graphic}
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

              <tr>
                <td style="padding:0 40px;">
                  <div style="border-top:1px solid {colors['line']};"></div>
                </td>
              </tr>

              <tr>
                <td style="padding:30px 40px;">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tbody>
                      <tr>
                        <td width="48" valign="top">
                          <div style="width:36px;height:36px;border-radius:50%;text-align:center;vertical-align:middle;background-color:{colors['sage']};">
                            {icon_shield}
                          </div>
                        </td>
                        <td valign="top" style="padding-left:12px;">
                          <p style="margin:0;color:{colors['brandDeep']};font-size:16px;line-height:1.3;font-weight:800;">Didn't request this?</p>
                          <p style="margin:4px 0 0;color:#66756D;font-size:14px;line-height:1.5;">
                            If you did not request a login, you can safely ignore this message.<br/>Your account will remain secure.
                          </p>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>

              <tr>
                <td style="padding:0 40px;">
                  <div style="border-top:1px solid {colors['line']};"></div>
                </td>
              </tr>

              <tr>
                <td style="padding:24px 40px 30px;">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tbody>
                      <tr>
                        <td valign="middle">
                          <p style="margin:0;color:{colors['brandDeep']};font-size:16px;line-height:1.3;font-weight:800;">Need help?</p>
                          <p style="margin:4px 0 0;color:#66756D;font-size:14px;line-height:1.5;">
                            Our support team is here for you.
                          </p>
                        </td>
                        <td align="right" valign="middle">
                          <a href="https://errandbridge.com/help" style="display:inline-block;padding:12px 24px;border-radius:24px;background-color:{colors['buttonBg']};color:{colors['buttonText']};text-decoration:none;font-size:14px;font-weight:700;border:1px solid {colors['sageDeep']};">
                            Visit Help Centre &rarr;
                          </a>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>

              <tr>
                <td style="padding:30px 20px;background-color:#FFFFFF;border-top:1px solid {colors['line']};">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tbody>
                      <tr>
                        <td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;border-right:1px solid {colors['line']};">
                          <div style="margin:0 auto 8px;width:24px;height:24px;">{icon_cart}</div>
                          <div style="font-size:12px;line-height:1.35;color:#65756D;font-weight:500;">Run errands</div>
                        </td>
                        <td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;border-right:1px solid {colors['line']};">
                          <div style="margin:0 auto 8px;width:24px;height:24px;">{icon_map}</div>
                          <div style="font-size:12px;line-height:1.35;color:#65756D;font-weight:500;">Track in real time</div>
                        </td>
                        <td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;border-right:1px solid {colors['line']};">
                          <div style="margin:0 auto 8px;width:24px;height:24px;">{icon_users}</div>
                          <div style="font-size:12px;line-height:1.35;color:#65756D;font-weight:500;">Trusted helpers</div>
                        </td>
                        <td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;">
                          <div style="margin:0 auto 8px;width:24px;height:24px;">{icon_shield}</div>
                          <div style="font-size:12px;line-height:1.35;color:#65756D;font-weight:500;">A safer community</div>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>
            </tbody>
          </table>
        </td>
      </tr>

      <tr>
        <td style="padding:40px 20px 20px;text-align:center;color:{colors['muted']};font-size:12px;line-height:1.65;">
          <img src="{logo_mark_url}" alt="ErrandBridge" width="32" height="32" style="display:block;margin:0 auto 12px;border:0;" onerror="this.outerHTML='<div style=\'font-size:24px;font-weight:800;color:{colors['brandDeep']};\'>🍃</div>'" />
          <div style="font-size:13px;font-weight:500;">Simple errands. Stronger communities.</div>
          <div style="margin-top:20px;font-size:16px;color:#A4B2AA;letter-spacing:10px;">
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg></a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"></path></svg></a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"></path><rect x="2" y="9" width="4" height="12"></rect><circle cx="4" cy="4" r="2"></circle></svg></a>
            <a href="#" style="color:inherit;text-decoration:none;display:inline-block;vertical-align:middle;"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"></path><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"></polygon></svg></a>
          </div>
          <div style="margin-top:20px;color:#90A097;">© 2026 ErrandBridge. All rights reserved. &nbsp;|&nbsp; <a href="https://errandbridge.com/privacy" style="color:#90A097;text-decoration:none;">Privacy Policy</a> &nbsp;|&nbsp; <a href="https://errandbridge.com/terms" style="color:#90A097;text-decoration:none;">Terms of Service</a> &nbsp;|&nbsp; <a href="https://errandbridge.com/unsubscribe" style="color:#90A097;text-decoration:none;">Unsubscribe</a></div>
        </td>
      </tr>
    </tbody>
  </table>
  
  <style>
    @media only screen and (max-width: 600px) {{
      .hide-on-mobile {{
        display: none !important;
      }}
    }}
  </style>
</div>
'''
