import unittest
import boto3
from moto import mock_aws
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.message import MIMEMessage
import os

class BaseAwsMockTest(unittest.TestCase):
    """
    すべてのAWSサービスをMotoでモック化したテストのベースクラス。
    どのテストでも共通となる初期処理をまとめる。
    """

    @classmethod
    def setUpClass(cls):
        """
        クラス実行時に一度だけ呼ばれる初期化処理。
        ここで環境変数の設定などを行う。
        """
        # --- 環境変数をセット ---
        os.environ["S3_BUCKET"] = "test-bucket"
        os.environ["S3_PATH"]   = "test"
        os.environ["AWS_DEFAULT_REGION"] = "ap-northeast-1"
        os.environ["MAIL_FORWARDS"] = '{"test@example.com": "forward@example.com", "test2@example.com": "forward2@example.com"}'
        os.environ["SENDER_EMAIL"] = "no-reply@example.com"

    def setUp(self):
        """
        各テストメソッドが実行されるたびに呼ばれる。
        """
        # モックを開始
        self.mock = mock_aws()
        self.mock.start()

        # --- モックされた S3クライアントを使ってバケット作成 ---
        s3_client = boto3.client("s3")
        s3_client.create_bucket(
            Bucket=os.environ['S3_BUCKET'],
            CreateBucketConfiguration={'LocationConstraint': os.environ['AWS_DEFAULT_REGION']}
        )

        # --- モックされた SESクライアントで送信元アドレスを「認証済み」に ---
        ses_client = boto3.client("ses")
        ses_client.verify_email_identity(EmailAddress=os.environ["SENDER_EMAIL"])

    def tearDown(self):
        """
        テストメソッド単位の後処理。必要に応じてモックをリセットしたり変数をクリアする。
        """
        # モックを停止
        self.mock.stop()

    @classmethod
    def tearDownClass(cls):
        """
        クラス単位の後処理。必要に応じてモックをリセットしたり変数をクリアする。
        """
        pass

class TestLambdaFunction(BaseAwsMockTest):

    def test_lambda_handler(self):
        """メール転送Lambda関数の呼び出しテスト"""

        # S3 上にテスト用のオブジェクトをアップロード
        s3_client = boto3.client("s3")
        s3_client.put_object(
            Bucket=os.environ['S3_BUCKET'],
            Key=f'{os.environ["S3_PATH"]}/abc',
            Body="""Return-Path: <sender@example.com>
MIME-Version: 1.0
From: sender <sender@example.com>
Date: Thu, 26 Dec 2024 15:37:40 +0900
Message-ID: <abc>
Subject: test
To: test <test@example.com>
Cc: test2 <test2@example.com>
Content-Type: multipart/mixed; boundary="0000000000005d6bdf062a269761"
X-AWS-SES-RECEIVING: transfer-email

--0000000000005d6bdf062a269761
Content-Type: multipart/alternative; boundary="0000000000005d6bde062a26975f"

--0000000000005d6bde062a26975f
Content-Type: text/plain; charset="UTF-8"
Content-Transfer-Encoding: base64

44GT44KM44GvDQoq44OG44K544OIKuOBp+OBmQ0K
--0000000000005d6bde062a26975f
Content-Type: text/html; charset="UTF-8"
Content-Transfer-Encoding: quoted-printable

<div dir=3D"ltr"><div class=3D"gmail_default" style=3D"font-family:&quot;ms=
 gothic&quot;,monospace"><span style=3D"font-family:&quot;ms pmincho&quot;,=
sans-serif">=E3=81=93=E3=82=8C=E3=81=AF</span></div><div class=3D"gmail_quo=
te gmail_quote_container"><div dir=3D"ltr"><div class=3D"gmail_quote"><div =
dir=3D"ltr"><div class=3D"gmail_quote"><div dir=3D"ltr"><div class=3D"gmail=
_quote"><div dir=3D"ltr"><div class=3D"gmail_quote"><div dir=3D"ltr"><div c=
lass=3D"gmail_quote"><div dir=3D"ltr"><div class=3D"gmail_quote"><div dir=
=3D"ltr"><div class=3D"gmail_quote"><div dir=3D"ltr"><div class=3D"gmail_qu=
ote"><div dir=3D"ltr"><div class=3D"gmail_quote"><div dir=3D"ltr"><div clas=
s=3D"gmail_quote"><div dir=3D"ltr"><div class=3D"gmail_quote"><div dir=3D"l=
tr"><div class=3D"gmail_quote"><div dir=3D"ltr"><div class=3D"gmail_quote">=
<div dir=3D"ltr"><div class=3D"gmail_quote"><div dir=3D"ltr"><div class=3D"=
gmail_quote"><div dir=3D"ltr"><div><font face=3D"comic sans ms, sans-serif"=
><b><i><u style=3D"background-color:rgb(255,255,0)">=E3=83=86=E3=82=B9=E3=
=83=88</u></i></b></font><font face=3D"ms pmincho, sans-serif">=E3=81=A7=E3=
=81=99</font></div></div></div></div></div></div></div></div></div></div></=
div></div></div></div></div></div></div></div></div></div></div></div></div=
></div></div></div></div></div></div></div></div></div></div></div>

--0000000000005d6bde062a26975f--
--0000000000005d6bdf062a269761
"""
        )

        # テストイベントを作成
        event = {
            'Records': [{
                "eventSource": "aws:ses",
                "eventVersion": "1.0",
                "ses": {
                    "mail": {
                        "messageId": "abc"
                    },
                    "receipt": {
                        "recipients": [
                            "test@example.com"
                        ]
                    }
                }
            }]
        }

        # Lambda関数をテスト
        from lambda_function import lambda_handler
        response = lambda_handler(event, None)
        self.assertEqual(response['statusCode'], 200)

class TestCreateForwardedMessage(BaseAwsMockTest):

    def setUp(self):
        """共通テストデータのセットアップ"""
        super().setUp()

        # テスト用のデータをセット
        self.original_recipient = "original@example.com"
        self.forward_to = "forwarded@example.com"
        self.sender_email = "sender@example.com"

        # テスト用のメールアドレスを認証済みにする
        ses_client = boto3.client("ses")
        ses_client.verify_email_identity(EmailAddress=self.sender_email)

    def test_single_message(self):
        """単一メッセージの転送テスト"""
        original_message = MIMEText("This is a test message.")
        original_message["Subject"] = "Test Subject"
        original_message["From"] = self.sender_email
        original_message["To"] = self.original_recipient

        from lambda_function import create_forwarded_message
        forwarded_message = create_forwarded_message(
            original_message, self.original_recipient, self.forward_to
        )

        self.assertIn("Fw: Test Subject", forwarded_message["Subject"])
        self.assertIn("forwarded@example.com", forwarded_message["To"])

    def test_message_with_attachment(self):
        """添付ファイル付きメッセージの転送テスト"""
        original_message = MIMEMultipart()
        original_message["Subject"] = "Test with Attachment"
        original_message["From"] = "sender@example.com"
        original_message["To"] = self.original_recipient

        attachment = MIMEText("Attachment content", "plain")
        attachment.add_header("Content-Disposition", "attachment", filename="test.txt")
        original_message.attach(attachment)

        from lambda_function import create_forwarded_message
        forwarded_message = create_forwarded_message(
            original_message, self.original_recipient, self.forward_to
        )

        self.assertIn("Fw: Test with Attachment", forwarded_message["Subject"])
        self.assertIn("forwarded@example.com", forwarded_message["To"])
        self.assertIn("test.txt", forwarded_message.as_string())

    def test_nested_multipart_message(self):
        """ネストされたマルチパートメッセージのテスト"""
        original_message = MIMEMultipart("mixed")
        original_message["Subject"] = "Nested Test"
        original_message["From"] = "sender@example.com"
        original_message["To"] = self.original_recipient

        # ネストされたマルチパート
        nested_message = MIMEMultipart("alternative")
        nested_message.attach(MIMEText("Plain text part", "plain"))
        nested_message.attach(MIMEText("<p>HTML part</p>", "html"))
        original_message.attach(nested_message)

        from lambda_function import create_forwarded_message
        forwarded_message = create_forwarded_message(
            original_message, self.original_recipient, self.forward_to
        )

        self.assertIn("Fw: Nested Test", forwarded_message["Subject"])
        self.assertIn("forwarded@example.com", forwarded_message["To"])
        self.assertIn("Plain text part", forwarded_message.as_string())
        self.assertIn("<p>HTML part</p>", forwarded_message.as_string())

    def test_rfc822_attachment(self):
        """message/rfc822形式の添付メッセージのテスト"""
        # 元のメッセージ
        inner_message = MIMEText("This is the attached email.")
        inner_message["Subject"] = "Attached Email"
        inner_message["From"] = "inner@example.com"
        inner_message["To"] = "recipient@example.com"

        # 添付として追加
        original_message = MIMEMultipart()
        original_message["Subject"] = "Email with Attached Email"
        original_message["From"] = "sender@example.com"
        original_message["To"] = self.original_recipient
        attachment = MIMEMessage(inner_message)
        original_message.attach(attachment)

        from lambda_function import create_forwarded_message
        forwarded_message = create_forwarded_message(
            original_message, self.original_recipient, self.forward_to
        )

        self.assertIn("Fw: Email with Attached Email", forwarded_message["Subject"])
        self.assertIn("forwarded@example.com", forwarded_message["To"])
        self.assertIn("Attached Email", forwarded_message.as_string())

    def test_complex_nested_structure(self):
        """複雑なメール構造のテスト"""
        original_message = MIMEMultipart("mixed")
        original_message["Subject"] = "Complex Nested Test"
        original_message["From"] = "sender@example.com"
        original_message["To"] = self.original_recipient

        # 第一階層
        level1_message = MIMEMultipart("related")
        level1_message.attach(MIMEText("Level 1 text content", "plain"))

        # 第二階層
        level2_message = MIMEMultipart("alternative")
        level2_message.attach(MIMEText("Level 2 plain text", "plain"))
        level2_message.attach(MIMEText("<p>Level 2 HTML content</p>", "html"))
        level1_message.attach(level2_message)

        # 第一階層をオリジナルメッセージに添付
        original_message.attach(level1_message)

        from lambda_function import create_forwarded_message
        forwarded_message = create_forwarded_message(
            original_message, self.original_recipient, self.forward_to
        )

        self.assertIn("Fw: Complex Nested Test", forwarded_message["Subject"])
        self.assertIn("forwarded@example.com", forwarded_message["To"])
        self.assertIn("Level 1 text content", forwarded_message.as_string())
        self.assertIn("Level 2 plain text", forwarded_message.as_string())
        self.assertIn("<p>Level 2 HTML content</p>", forwarded_message.as_string())

    def test_unsupported_format(self):
        """未対応の形式の処理テスト"""
        original_message = MIMEText("Unsupported format test")
        original_message["Content-Type"] = "application/unsupported"
        original_message["Subject"] = "Unsupported Test"
        original_message["From"] = "sender@example.com"
        original_message["To"] = self.original_recipient

        from lambda_function import create_forwarded_message
        forwarded_message = create_forwarded_message(
            original_message, self.original_recipient, self.forward_to
        )

        self.assertIn("Fw: Unsupported Test", forwarded_message["Subject"])
        self.assertIn("forwarded@example.com", forwarded_message["To"])

if __name__ == '__main__':
    unittest.main()