import json
import os
import boto3
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import decode_header
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

def create_forwarded_message(original_message, original_recipient, forward_to):
    """転送用の新規メールメッセージを作成"""
    msg = MIMEMultipart()

    # 基本ヘッダーの設定
    msg['Subject'] = f"Fw: {original_message['Subject']}"
    msg['From'] = f"\"{decode_email_header(original_message['From'])}\" <{os.environ.get('SENDER_EMAIL', 'no-reply@example.com')}>"
    msg['Reply-To'] = original_message['From']
    msg['To'] = forward_to

    # オリジナルメールのヘッダー情報を取得
    important_header_keys = ['Date', 'Subject', 'From', 'To', 'Cc']
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
    for header in ['Date', 'Message-ID', 'Subject', 'From', 'Reply-To', 'To', 'Cc']:
        if header in original_message:
            msg[f'X-Original-{header}'] = original_message[header]

    # オリジナルのマルチパートメッセージをそのまま添付（ネスト）
    if original_message.is_multipart():
        # オリジナルが multipart/alternative の場合
        if original_message.get_content_type() == 'multipart/alternative':
            alternative_part = MIMEMultipart('alternative')
            for part in original_message.get_payload():
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    if payload is not None:
                        decoded_payload = payload.decode(charset, errors='replace')
                    else:
                        decoded_payload = ""
                except Exception as e:
                    logger.error(f"パートのデコード中にエラーが発生: {str(e)}")
                    decoded_payload = ""
                new_part = MIMEText(
                    decoded_payload,
                    _subtype=part.get_content_subtype(),
                    _charset=part.get_content_charset() or 'utf-8'
                )
                for key, value in part.items():
                    new_part[key] = value
                alternative_part.attach(new_part)
            msg.attach(alternative_part)
        # その他の multipart の場合
        else:
            nested_msg = MIMEMultipart(original_message.get_content_subtype())
            for part in original_message.walk():
                if part.get_content_maintype() == 'multipart':
                    continue  # ネストされた multipart をスキップ
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    if payload is not None:
                        decoded_payload = payload.decode(charset, errors='replace')
                    else:
                        decoded_payload = ""
                except Exception as e:
                    logger.error(f"パートのデコード中にエラーが発生: {str(e)}")
                    decoded_payload = ""
                new_part = MIMEText(
                    decoded_payload,
                    _subtype=part.get_content_subtype(),
                    _charset=part.get_content_charset() or 'utf-8'
                )
                for key, value in part.items():
                    new_part[key] = value
                nested_msg.attach(new_part)
            msg.attach(nested_msg)
    else:
        # シングルパートの場合、直接添付
        msg.attach(MIMEText(
            original_message.get_payload(decode=True).decode(original_message.get_content_charset() or 'utf-8', errors='replace'),
            _subtype=original_message.get_content_subtype(),
            _charset=original_message.get_content_charset() or 'utf-8'
        ))

    # # オリジナルメールを添付
    # original_part = MIMEApplication(original_message.as_string(), _subtype='octet-stream')
    # original_part.add_header('Content-Disposition', 'attachment', filename='forwarded_message.eml')
    # msg.attach(original_part)

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

            # SESでメールを送信
            response = ses_client.send_raw_email(
                Source=forwarded_message['From'],
                Destinations=[forward_to],
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