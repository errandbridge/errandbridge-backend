
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
    icon_cart = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path></svg>'''
    icon_map = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>'''
    icon_users = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>'''
    icon_shield = '''<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1F6C4C" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>'''

    # Shield graphic SVGs for the right side
    shield_graphic = '''
    <div style="background-color:#E9F5E3; border-radius: 40% 40% 40% 40% / 60% 60% 40% 40%; width: 140px; height: 160px; position: relative; margin: 0 auto; text-align: center; padding-top: 30px; box-sizing: border-box;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="#1F6C4C" stroke="#1F6C4C" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path><rect x="9" y="10" width="6" height="7" rx="1" fill="#FFFFFF"></rect><path d="M10 10V8a2 2 0 0 1 4 0v2" stroke="#FFFFFF" fill="none"></path></svg>
        <div style="margin-top:15px; font-family: 'Caveat', 'Comic Sans MS', cursive; font-size: 16px; color:#1F6C4C; transform: rotate(-8deg);">You're in safe hands</div>
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
                          Here's your<br />security code
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
                            This code will expire in <strong style="color:{colors['brandDeep']};">{expires_in_minutes} minutes</strong>.
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
                <td style="padding:30px 20px;background-color:#FAFCF8;border-top:1px solid {colors['line']};">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tbody>
                      <tr>
                        <td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;">
                          <div style="margin:0 auto 8px;width:24px;height:24px;">{icon_cart}</div>
                          <div style="font-size:12px;line-height:1.35;color:#65756D;font-weight:500;">Run errands</div>
                        </td>
                        <td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;">
                          <div style="margin:0 auto 8px;width:24px;height:24px;">{icon_map}</div>
                          <div style="font-size:12px;line-height:1.35;color:#65756D;font-weight:500;">Track in real time</div>
                        </td>
                        <td style="width:25%;padding:0 8px;text-align:center;vertical-align:top;">
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
            <a href="#" style="color:inherit;text-decoration:none;">𝕏</a>
            <a href="#" style="color:inherit;text-decoration:none;">📷</a>
            <a href="#" style="color:inherit;text-decoration:none;">f</a>
            <a href="#" style="color:inherit;text-decoration:none;">in</a>
            <a href="#" style="color:inherit;text-decoration:none;">▶</a>
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
