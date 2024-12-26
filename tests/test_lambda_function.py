import unittest
from unittest.mock import patch
import boto3
from moto import mock_s3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.message import MIMEMessage
from lambda_function import lambda_handler, create_forwarded_message

class TestLambdaFunction(unittest.TestCase):
    @mock_s3
    def test_lambda_handler(self):
        # S3バケットをモックで作成
        s3 = boto3.client('s3')
        s3.create_bucket(
            Bucket='test-bucket',
            CreateBucketConfiguration={'LocationConstraint': 'ap-northeast-1'}
        )

        # テストデータをアップロード
        s3.put_object(
            Bucket='test-bucket',
            Key='test.txt',
            Body='test content'
        )

        # Lambda関数をテスト
        event = {
            'Records': [{
                's3': {
                    'bucket': {'name': 'test-bucket'},
                    'object': {'key': 'test.txt'}
                }
            }]
        }

        response = lambda_handler(event, None)
        self.assertEqual(response['statusCode'], 200)

class TestCreateForwardedMessage(unittest.TestCase):
    def setUp(self):
        """共通テストデータのセットアップ"""
        self.original_recipient = "original@example.com"
        self.forward_to = "forwarded@example.com"

    def test_single_message(self):
        """単一メッセージの転送テスト"""
        original_message = MIMEText("This is a test message.")
        original_message["Subject"] = "Test Subject"
        original_message["From"] = "sender@example.com"
        original_message["To"] = self.original_recipient

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

        forwarded_message = create_forwarded_message(
            original_message, self.original_recipient, self.forward_to
        )

        self.assertIn("Fw: Unsupported Test", forwarded_message["Subject"])
        self.assertIn("forwarded@example.com", forwarded_message["To"])

if __name__ == '__main__':
    unittest.main()