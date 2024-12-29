import json
import os
import boto3
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.message import MIMEMessage
from email.header import decode_header
from email.header import Header
from email.utils import formataddr
from email import message_from_bytes, message_from_string
from email.message import Message
from email.errors import MessageParseError
from botocore.exceptions import ClientError
import logging

# ロガーの設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS サービスのクライアント初期化
s3_client = boto3.client('s3')
ses_client = boto3.client('ses')

def get_email_forwards():
    """環境変数からメール転送設定を取得"""
    forwards = os.environ.get('MAIL_FORWARDS', '{}')
    try:
        return json.loads(forwards)
    except json.JSONDecodeError:
        logger.error("MAIL_FORWARDS環境変数の解析に失敗しました")
        return {}

def get_message_from_s3(bucket, key):
    """S3からメールデータを取得"""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response['Body'].read().decode('utf-8')
    except ClientError as e:
        logger.error(f"S3からのメール取得に失敗: {str(e)}")
        raise

def decode_email_header(header_value):
    """メールヘッダーをデコード"""
    if not header_value:
        return ""  # 空のヘッダーには空文字を返す
    decoded_fragments = decode_header(header_value)
    decoded_string = ""
    for fragment, encoding in decoded_fragments:
        if isinstance(fragment, bytes):
            # バイナリの場合、指定されたエンコーディングでデコード（デフォルトはUTF-8）
            decoded_string += fragment.decode(encoding or 'utf-8', errors='replace')
        else:
            # すでに文字列型ならそのまま結合
            decoded_string += fragment
    return decoded_string

def decode_parts(parent, message):
    """メッセージを再帰的に処理"""
    if message.get_content_type() == "message/rfc822":
        # 添付ファイルの場合
        logger.debug(f"添付メッセージ: {message.get_content_type()} / {message.get_content_subtype()}")
        try:
            # logger.debug(f"message: {message}")
            payload = message.get_payload(decode=False)  # 生データを取得
            # logger.debug(f"payload: {payload}")
            if not isinstance(payload, list):
                payload = [payload]

            for part in payload:
                if isinstance(part, bytes):
                    # バイナリデータをパース
                    # logger.debug(f"binary part: {part}")
                    inner_message = message_from_bytes(part)
                elif isinstance(part, str):
                    # 文字列データをパース
                    # logger.debug(f"string part: {part}")
                    inner_message = message_from_string(part)
                elif isinstance(part, Message):
                    # すでに Message オブジェクトの場合
                    # logger.debug(f"message part: {part}")
                    inner_message = part
                else:
                    # 未対応の型
                    logger.warning(f"Unsupported part type: {type(part)}")
                    continue

                # logger.debug(f"inner_message: {inner_message}")
                attachment = MIMEMessage(inner_message)
                # logger.debug(f"attachment: {attachment}")

                # ヘッダーの設定
                filename = decode_email_header(message.get_param('filename') or message.get_param('name') or 'attached_message.eml')
                attachment.add_header('Content-Disposition', 'attachment', filename=filename)
                # logger.debug(f"attachment: {attachment}")

                parent.attach(attachment)

        except (MessageParseError, TypeError) as e:
            logger(f"Failed to process message/rfc822 attachment: {e}")

    elif message.is_multipart():
        # マルチパートの場合
        logger.debug(f"マルチパートメッセージ: {message.get_content_type()} / {message.get_content_subtype()}")
        new_part = MIMEMultipart(message.get_content_subtype())
        for part in message.get_payload():
            decode_parts(new_part, part)  # 再帰的に添付
        parent.attach(new_part)
    else:
        # シングルパートの場合
        logger.debug(f"シングルパートメッセージ: {message.get_content_type()} / {message.get_content_subtype()}")
        try:
            payload = message.get_payload(decode=True)
            charset = message.get_content_charset() or 'utf-8'
            subtype = message.get_content_subtype()
            if payload:
                decoded_payload = payload.decode(charset, errors='replace')
            else:
                decoded_payload = ""
        except Exception as e:
            logger.error(f"パートのデコード中にエラーが発生: {str(e)}")
            decoded_payload = ""

        decoded_part = MIMEText(decoded_payload, _subtype=subtype, _charset=charset)
        for key, value in message.items():
            decoded_part[key] = value

        parent.attach(decoded_part)

def create_forwarded_message(original_message, original_recipient, forward_to):
    """転送用の新規メールメッセージを作成"""
    msg = MIMEMultipart()

    # 基本ヘッダーの設定
    msg['Subject'] = f"Fw: {original_message['Subject']}"
    msg['From'] = formataddr((
        str(Header(decode_email_header(original_message['From']), 'utf-8')),
        os.environ.get('SENDER_EMAIL', 'no-reply@example.com')
    ))
    msg['Reply-To'] = original_message['From']
    msg['To'] = forward_to

    # オリジナルメールのヘッダー情報を取得
    important_header_keys = ['Date', 'Subject', 'From', 'Reply-To', 'To', 'Cc', 'Bcc']
    important_headers = "\n".join(
        f"{header}: {decode_email_header(original_message[header])}"
        for header in important_header_keys if header in original_message
    )
    # original_headers = "\n".join(
    #     f"{header}: {decode_email_header(original_message[header])}"
    #     for header in original_message.keys() if header not in important_header_keys
    # )

    # 転送用本文の作成
    info_text = f"""
Original Recipient: {original_recipient}
Forwarded To: {forward_to}

--- Original Message ---
{important_headers}

"""
    msg.attach(MIMEText(info_text, 'plain'))

    # 重要なヘッダーの転送
    important_header_keys.append('Message-ID')
    for header in important_header_keys:
        if header in original_message:
            msg[f'X-Original-{header}'] = original_message[header]

    decode_parts(msg, original_message)

    return msg

def lambda_handler(event, context):
    """Lambda関数のメインハンドラー"""
    try:
        for record in event['Records']:
            # S3イベントからメール情報を取得
            ses_notification = record['ses']
            receipt = ses_notification['receipt']
            mail = ses_notification['mail']

            # メールの受信者アドレスを取得
            original_recipient = receipt['recipients'][0]

            # 転送設定を確認
            forwards = get_email_forwards()
            if original_recipient not in forwards:
                logger.warning(f"転送先が設定されていないアドレス: {original_recipient}")
                return {
                    'statusCode': 200,
                    'body': json.dumps('No forward address configured')
                }

            forward_to = forwards[original_recipient]

            # S3からメールデータを取得
            bucket = os.environ.get('S3_BUCKET')
            key = f'{os.environ.get('S3_PATH')}/{mail['messageId']}'
            email_data = get_message_from_s3(bucket, key)

            # オリジナルメールをパース
            original_message = email.message_from_string(email_data)

            # 転送用メールを作成
            forwarded_message = create_forwarded_message(original_message, original_recipient, forward_to)

            # # 送信時にカンマで分割してリスト化
            # forward_to_list = [addr.strip() for addr in forward_to.split(',')]

            # SESでメールを送信
            response = ses_client.send_raw_email(
                Source=forwarded_message['From'],
                # create_forwarded_message 関数で、MIMEヘッダ 'To' に指定されているので、重複指定を避ける
                # MIMEヘッダでは指定していないアドレスを送信先に含める場合には、Destinations にリストで指定する
                # Destinations=forward_to_list,
                RawMessage={'Data': forwarded_message.as_string()}
            )

            logger.info(f"メール転送成功: {response['MessageId']}")
            return {
                'statusCode': 200,
                'body': json.dumps('Email forwarded successfully')
            }

    except Exception as e:
        logger.error(f"メール転送中にエラーが発生: {str(e)}")
        raise