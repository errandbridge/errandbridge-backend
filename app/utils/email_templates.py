def get_security_code_email(code: str, expires_in_minutes: int = 10) -> str:
    # Ensure code is exactly 6 digits by padding or truncating if needed
    safe_code = str(code).ljust(6, "•")[:6]
    digits = list(safe_code)

    colors = {
        "brand": "#0D4A35",
        "brandDeep": "#083526",
        "brandMid": "#4B7A57",
        "lime": "#D9F23A",
        "limeSoft": "#F3F9CF",
        "sage": "#EEF4EC",
        "sageDeep": "#DCE9DA",
        "paper": "#FCFDF9",
        "text": "#123226",
        "muted": "#718078",
        "line": "#DDE7DC",
        "white": "#FFFFFF",
    }

    # Generate the digit cells dynamically
    digit_cells = "".join(
        [
            f'<td style="width:16.666%;height:64px;text-align:center;vertical-align:middle;border:1px solid #9BBCA5;border-radius:10px;background-color:{colors["paper"]};color:{colors["brandDeep"]};font-size:30px;line-height:1;font-weight:800;">{digit}</td>'
            for digit in digits
        ]
    )

    return f"""
<div style="margin:0;padding:32px 12px;width:100%;background-color:{colors['sage']};font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, Helvetica, sans-serif;color:{colors['text']};">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:680px;margin:0 auto;border-collapse:collapse;">
    <tbody>
      <tr>
        <td style="padding:0 8px 18px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
            <tbody>
              <tr>
                <td style="vertical-align:middle;">
                  <div style="font-size:28px;font-weight:800;color:{colors['brandDeep']};letter-spacing:-0.6px;">ErrandBridge</div>
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
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;background-color:{colors['white']};border:1px solid {colors['line']};border-radius:14px;overflow:hidden;box-shadow:0 12px 30px rgba(13, 74, 53, 0.07);">
            <tbody>
              <tr>
                <td style="padding:38px 38px 30px;background:linear-gradient(135deg, #FFFFFF 0%, #FFFFFF 62%, #F4F8EF 100%);">
                  <p style="margin:0;color:{colors['muted']};font-size:12px;font-weight:800;letter-spacing:3px;text-transform:uppercase;">Security code</p>
                  <h1 style="margin:12px 0 10px;color:{colors['brandDeep']};font-size:38px;line-height:1.08;font-weight:800;letter-spacing:-1px;">
                    Here's your<br />security code
                  </h1>
                  <p style="margin:0;max-width:480px;color:#56655E;font-size:17px;line-height:1.6;">
                    Use the code below to continue signing in to your ErrandBridge account.
                  </p>
                  <div style="margin-top:26px;padding:22px;border-radius:12px;background-color:{colors['sage']};border:1px solid {colors['sageDeep']};">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:8px 0;">
                      <tbody>
                        <tr>
                          {digit_cells}
                        </tr>
                      </tbody>
                    </table>
                    <p style="margin:16px 0 0;text-align:center;color:#5E6D65;font-size:14px;line-height:1.5;">
                      This code will expire in <strong style="color:{colors['brandDeep']};">{expires_in_minutes} minutes</strong>.
                    </p>
                  </div>
                </td>
              </tr>

              <tr>
                <td style="padding:28px 38px;border-top:1px solid {colors['line']};">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tbody>
                      <tr>
                        <td width="60" valign="top">
                          <div style="width:46px;height:46px;border-radius:50%;text-align:center;vertical-align:middle;background-color:{colors['sage']};color:{colors['brand']};font-size:22px;font-weight:800;line-height:46px;">✓</div>
                        </td>
                        <td valign="top">
                          <p style="margin:0;color:{colors['brandDeep']};font-size:17px;line-height:1.3;font-weight:800;">Didn't request this?</p>
                          <p style="margin:5px 0 0;color:#66756D;font-size:14px;line-height:1.55;">
                            If you did not request a login, you can safely ignore this message. Your account will remain secure.
                          </p>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>

              <tr>
                <td style="padding:24px 38px 30px;border-top:1px solid {colors['line']};">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tbody>
                      <tr>
                        <td valign="middle">
                          <p style="margin:0;color:{colors['brandDeep']};font-size:17px;line-height:1.3;font-weight:800;">Need help?</p>
                          <p style="margin:5px 0 0;color:#66756D;font-size:14px;line-height:1.55;">
                            Our support team is here for you.
                          </p>
                        </td>
                        <td align="right" valign="middle">
                          <a href="https://errandbridge.com/help" style="display:inline-block;padding:12px 18px;border-radius:9px;background-color:{colors['brand']};color:{colors['white']};text-decoration:none;font-size:14px;font-weight:800;">
                            Visit Help Centre →
                          </a>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </td>
              </tr>

              <tr>
                <td style="padding:22px 16px;background-color:{colors['paper']};border-top:1px solid {colors['line']};">
                  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                    <tbody>
                      <tr>
                        <td style="width:25%;padding:6px 8px;text-align:center;vertical-align:top;color:{colors['brandDeep']};">
                          <div style="font-size:22px;line-height:1;">🛒</div>
                          <div style="margin-top:7px;font-size:12px;line-height:1.35;color:#65756D;">Run errands</div>
                        </td>
                        <td style="width:25%;padding:6px 8px;text-align:center;vertical-align:top;color:{colors['brandDeep']};">
                          <div style="font-size:22px;line-height:1;">⌖</div>
                          <div style="margin-top:7px;font-size:12px;line-height:1.35;color:#65756D;">Track in real time</div>
                        </td>
                        <td style="width:25%;padding:6px 8px;text-align:center;vertical-align:top;color:{colors['brandDeep']};">
                          <div style="font-size:22px;line-height:1;">👥</div>
                          <div style="margin-top:7px;font-size:12px;line-height:1.35;color:#65756D;">Trusted helpers</div>
                        </td>
                        <td style="width:25%;padding:6px 8px;text-align:center;vertical-align:top;color:{colors['brandDeep']};">
                          <div style="font-size:22px;line-height:1;">✓</div>
                          <div style="margin-top:7px;font-size:12px;line-height:1.35;color:#65756D;">A safer community</div>
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
        <td style="padding:24px 20px 6px;text-align:center;color:{colors['muted']};font-size:12px;line-height:1.65;">
          <div style="font-size:18px;font-weight:800;color:{colors['brandDeep']};">ErrandBridge</div>
          <div style="margin-top:3px;">Simple errands. Stronger communities.</div>
          <div style="width:56px;height:4px;margin:18px auto 0;border-radius:999px;background-color:{colors['lime']};"></div>
          <div style="margin-top:18px;">© 2026 ErrandBridge. All rights reserved.</div>
          <div style="margin-top:6px;">
            <a href="https://errandbridge.com/privacy" style="color:{colors['brand']};text-decoration:none;margin:0 8px;font-weight:700;">Privacy Policy</a>
            <span>•</span>
            <a href="https://errandbridge.com/terms" style="color:{colors['brand']};text-decoration:none;margin:0 8px;font-weight:700;">Terms of Service</a>
            <span>•</span>
            <a href="https://errandbridge.com/unsubscribe" style="color:{colors['brand']};text-decoration:none;margin:0 8px;font-weight:700;">Unsubscribe</a>
          </div>
        </td>
      </tr>
    </tbody>
  </table>
</div>
"""
