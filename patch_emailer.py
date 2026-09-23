import sys

with open("app/services/emailer.py", "r") as f:
    content = f.read()

content = content.replace(
    "def send_email(*, to_email: str, subject: str, body_text: str) -> SendResult:",
    "def send_email(*, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> SendResult:"
)

content = content.replace(
    "result = _send_via_graph(\n            to_email=to_email, subject=subject, body_text=body_text\n        )",
    "result = _send_via_graph(\n            to_email=to_email, subject=subject, body_text=body_text, body_html=body_html\n        )"
)

content = content.replace(
    "result = _send_via_smtp(to_email=to_email, subject=subject, body_text=body_text)",
    "result = _send_via_smtp(to_email=to_email, subject=subject, body_text=body_text, body_html=body_html)"
)

content = content.replace(
    "def _send_via_graph(*, to_email: str, subject: str, body_text: str) -> SendResult:",
    "def _send_via_graph(*, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> SendResult:"
)

graph_body_replace = """                    "body": {"contentType": "Text", "content": body_text},"""
graph_body_new = """                    "body": {"contentType": "HTML" if body_html else "Text", "content": body_html or body_text},"""
content = content.replace(graph_body_replace, graph_body_new)

content = content.replace(
    "def _send_via_smtp(*, to_email: str, subject: str, body_text: str) -> SendResult:",
    "def _send_via_smtp(*, to_email: str, subject: str, body_text: str, body_html: str | None = None) -> SendResult:"
)

msg_set_content_replace = """        msg.set_content(body_text)"""
msg_set_content_new = """        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")"""
content = content.replace(msg_set_content_replace, msg_set_content_new)

with open("app/services/emailer.py", "w") as f:
    f.write(content)

