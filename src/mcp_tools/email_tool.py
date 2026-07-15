"""Email MCP 工具 — 邮件收发

支持 SMTP 发送、IMAP 接收。
"""
import email
import imaplib
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
from typing import Callable, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.agent.tools import PermissionChecker
from src.config import settings
from src.mcp_tools.common import format_result, require_admin

logger = logging.getLogger(__name__)


def _decode_mime_str(s: str) -> str:
    """解码 MIME 编码的字符串"""
    if not s:
        return ""
    parts = decode_header(s)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _send_smtp(to_addrs: List[str], subject: str, body: str, html: bool = False) -> tuple[bool, str]:
    """通过 SMTP 发送邮件"""
    try:
        msg = MIMEMultipart()
        msg["From"] = settings.mcp_email_from_addr or settings.mcp_email_username
        msg["To"] = ", ".join(to_addrs)
        msg["Subject"] = subject

        content_type = "html" if html else "plain"
        msg.attach(MIMEText(body, content_type, "utf-8"))

        if settings.mcp_email_smtp_ssl:
            server = smtplib.SMTP_SSL(settings.mcp_email_smtp_host, settings.mcp_email_smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(settings.mcp_email_smtp_host, settings.mcp_email_smtp_port, timeout=15)
            server.starttls()

        if settings.mcp_email_username:
            server.login(settings.mcp_email_username, settings.mcp_email_password)

        server.sendmail(msg["From"], to_addrs, msg.as_string())
        server.quit()
        return True, "发送成功"
    except Exception as e:
        logger.error("Email send error: %s", e)
        return False, str(e)


def _imap_connect() -> Optional[imaplib.IMAP4]:
    """建立 IMAP 连接"""
    try:
        if settings.mcp_email_imap_ssl:
            mail = imaplib.IMAP4_SSL(settings.mcp_email_imap_host, settings.mcp_email_imap_port, timeout=15)
        else:
            mail = imaplib.IMAP4(settings.mcp_email_imap_host, settings.mcp_email_imap_port, timeout=15)
            mail.starttls()

        mail.login(settings.mcp_email_username, settings.mcp_email_password)
        return mail
    except Exception as e:
        logger.error("IMAP connect error: %s", e)
        return None


def create_email_tools(
    user_id: str = "",
    tenant_id: str = "",
    roles: Optional[List[str]] = None,
    plan: str = "free",
    authority_source: Optional[Callable] = None,
) -> List:
    """创建邮件收发工具集"""
    checker = PermissionChecker(
        user_id=user_id, tenant_id=tenant_id, roles=roles or [], plan=plan,
        authority_source=authority_source,
    )

    if not settings.mcp_email_enabled:
        @tool
        def email_send(to: str, subject: str, body: str) -> str:
            """邮件工具（未启用）。"""
            return format_result("未启用", "Email MCP 服务未启用，请在配置中开启 mcp_email_enabled")

        return [email_send]

    @tool
    def email_send(to: str, subject: str, body: str, cc: str = "") -> str:
        """发送纯文本邮件。

        何时使用：需要给用户发送普通文本邮件通知时。

        Args:
            to: 收件人，多个用逗号分隔
            subject: 邮件主题
            body: 邮件正文
            cc: 抄送，多个用逗号分隔
        """
        if not checker.check("email_send"):
            return format_result("权限不足", "您没有权限发送邮件")

        to_list = [t.strip() for t in to.split(",") if t.strip()]
        if not to_list:
            return format_result("参数错误", "收件人不能为空")

        all_recipients = to_list[:]
        if cc:
            cc_list = [c.strip() for c in cc.split(",") if c.strip()]
            all_recipients.extend(cc_list)

        success, msg = _send_smtp(all_recipients, subject, body, html=False)
        if success:
            return format_result("发送成功", f"已发送到 {len(all_recipients)} 个收件人")
        return format_result("发送失败", msg)

    @tool
    def email_send_html(to: str, subject: str, html_body: str, cc: str = "") -> str:
        """发送 HTML 格式邮件。

        何时使用：需要发送富文本格式邮件（带样式、表格等）时。

        Args:
            to: 收件人，多个用逗号分隔
            subject: 邮件主题
            html_body: HTML 格式正文
            cc: 抄送，多个用逗号分隔
        """
        if not checker.check("email_send_html"):
            return format_result("权限不足", "您没有权限发送邮件")

        to_list = [t.strip() for t in to.split(",") if t.strip()]
        if not to_list:
            return format_result("参数错误", "收件人不能为空")

        all_recipients = to_list[:]
        if cc:
            cc_list = [c.strip() for c in cc.split(",") if c.strip()]
            all_recipients.extend(cc_list)

        success, msg = _send_smtp(all_recipients, subject, html_body, html=True)
        if success:
            return format_result("发送成功", f"已发送 HTML 邮件到 {len(all_recipients)} 个收件人")
        return format_result("发送失败", msg)

    @tool
    def email_list_inbox(limit: int = 20, folder: str = "INBOX") -> str:
        """列出收件箱邮件列表。

        何时使用：需要查看收件箱有哪些邮件时。

        Args:
            limit: 返回数量，默认 20
            folder: 邮件夹，默认 INBOX
        """
        if not checker.check("email_list_inbox"):
            return format_result("权限不足", "您没有权限查看邮件")

        mail = _imap_connect()
        if mail is None:
            return format_result("连接失败", "无法连接到 IMAP 服务器")

        try:
            mail.select(folder)
            status, data = mail.search(None, "ALL")
            if status != "OK":
                return format_result("查询失败", f"搜索邮件失败: {status}")

            msg_ids = data[0].split()
            msg_ids = msg_ids[-limit:] if msg_ids else []
            msg_ids.reverse()

            lines = [f"[收件箱] {folder} 共 {len(data[0].split())} 封，显示前 {len(msg_ids)} 封:"]
            for msg_id in msg_ids:
                status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if status == "OK" and msg_data[0]:
                    raw = msg_data[0][1].decode("utf-8", errors="replace")
                    msg_obj = email.message_from_string(raw)
                    sender = _decode_mime_str(msg_obj.get("From", ""))
                    subject = _decode_mime_str(msg_obj.get("Subject", ""))
                    date = msg_obj.get("Date", "")
                    lines.append(f"  • [{msg_id.decode()}] {subject[:60]}")
                    lines.append(f"    来自: {sender} | {date}")

            return "\n".join(lines)
        except Exception as e:
            logger.error("Email list error: %s", e)
            return format_result("查询失败", str(e))
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    @tool
    def email_get_content(msg_id: str, folder: str = "INBOX") -> str:
        """读取邮件完整内容。

        何时使用：需要查看某封邮件的完整正文时。

        Args:
            msg_id: 邮件 ID（从 email_list_inbox 获取）
            folder: 邮件夹，默认 INBOX
        """
        if not checker.check("email_get_content"):
            return format_result("权限不足", "您没有权限查看邮件")

        mail = _imap_connect()
        if mail is None:
            return format_result("连接失败", "无法连接到 IMAP 服务器")

        try:
            mail.select(folder)
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                return format_result("读取失败", f"无法读取邮件 {msg_id}")

            raw_email = msg_data[0][1]
            msg_obj = email.message_from_bytes(raw_email)

            subject = _decode_mime_str(msg_obj.get("Subject", ""))
            sender = _decode_mime_str(msg_obj.get("From", ""))
            recipient = _decode_mime_str(msg_obj.get("To", ""))
            date = msg_obj.get("Date", "")

            body = ""
            if msg_obj.is_multipart():
                for part in msg_obj.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
                if not body:
                    for part in msg_obj.walk():
                        if part.get_content_type() == "text/html":
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            body = payload.decode(charset, errors="replace")
                            break
            else:
                payload = msg_obj.get_payload(decode=True)
                charset = msg_obj.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")

            return format_result("邮件内容", "", {
                "subject": subject,
                "from": sender,
                "to": recipient,
                "date": date,
                "body": body[:3000],
            })
        except Exception as e:
            logger.error("Email read error: %s", e)
            return format_result("读取失败", str(e))
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    @tool
    def email_search(keyword: str, folder: str = "INBOX", limit: int = 20) -> str:
        """搜索邮件（按主题或内容关键词）。

        何时使用：需要从邮件中查找特定内容时。

        Args:
            keyword: 搜索关键词
            folder: 邮件夹，默认 INBOX
            limit: 返回数量，默认 20
        """
        if not checker.check("email_search"):
            return format_result("权限不足", "您没有权限搜索邮件")

        mail = _imap_connect()
        if mail is None:
            return format_result("连接失败", "无法连接到 IMAP 服务器")

        try:
            mail.select(folder)
            status, data = mail.search(None, f'SUBJECT "{keyword}"')
            if status != "OK":
                return format_result("搜索失败", f"搜索邮件失败: {status}")

            msg_ids = data[0].split()
            msg_ids = msg_ids[-limit:] if msg_ids else []
            msg_ids.reverse()

            lines = [f"[搜索结果] 关键词: {keyword}，共 {len(data[0].split())} 封:"]
            for msg_id in msg_ids:
                status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if status == "OK" and msg_data[0]:
                    raw = msg_data[0][1].decode("utf-8", errors="replace")
                    msg_obj = email.message_from_string(raw)
                    subject = _decode_mime_str(msg_obj.get("Subject", ""))
                    sender = _decode_mime_str(msg_obj.get("From", ""))
                    lines.append(f"  • [{msg_id.decode()}] {subject[:60]} ({sender})")

            return "\n".join(lines)
        except Exception as e:
            logger.error("Email search error: %s", e)
            return format_result("搜索失败", str(e))
        finally:
            try:
                mail.logout()
            except Exception:
                pass

    return [
        email_send,
        email_send_html,
        email_list_inbox,
        email_get_content,
        email_search,
    ]
