# AWS Lambda SES Email Transfer

AWS Simple Email Service (SES) で受信したメールを、AWS Lambda を使用して別のメールアドレスに転送するスクリプトです。GitHub Actionsを利用したCI/CDパイプラインも用意しています。

## プロジェクト概要

このプロジェクトは以下のコンポーネントで構成されています：

- AWS Lambda 関数によるメール転送処理（Python）
- motoライブラリを使用したテスト
- GitHub Actionsを使用したCI/CDパイプライン

## 機能

- SESで受信したメールを指定したメールアドレスに転送
- 元のメールの形式（テキスト/HTML）を保持
- 添付ファイルの転送対応
- 複数の転送先設定が可能
- オリジナルメールのヘッダー情報を保持

## セットアップ

### 前提条件

- AWS アカウント
- 設定済みの AWS SES ドメイン
- SES 受信ルールによる S3 バケットへのメール保存

### 必要な AWS サービス

- AWS Lambda
- AWS SES
- AWS S3
- IAM（適切な権限設定）

### 環境変数の設定

Lambda 関数に以下の環境変数を設定する必要があります：

- `MAIL_FORWARDS`: 転送設定を JSON 形式で指定
  ```json
  {
    "receive@example.com": "forward@example.com"
  }
  ```
  - 転送元メールアドレスをkeyとし、転送先メールアドレスをvalueとして指定
  - 複数の転送対象アドレスについて転送設定する場合は、複数のkey-valueを指定
  - ひとつの転送対象アドレスについて複数の転送先アドレスを指定する場合は、転送先をカンマ区切りで指定
- `SENDER_EMAIL`: 転送メールの送信元アドレス
  - SESで送信可能なメールアドレス
- `S3_BUCKET`: メールを一時保存する S3 バケット名
- `S3_PATH`: S3 バケット内のパス

### 必要な IAM 権限

Lambda 実行ロールには以下の権限が必要です：

- `ses:SendRawEmail`
- `s3:GetObject`
- CloudWatch Logs へのアクセス権限

## デプロイ方法

0. 適切な IAM 権限の設定
1. AWS Lambda に `lambda_package.zip` をアップロード
2. 環境変数を設定
3. SES の受信ルールセットを設定
   1. S3 バケットへメール保存する設定
   2. Lambda 関数を呼び出す設定

## 使用方法

1. SES で設定した受信ルールに対してメールを送信
2. 環境変数 `MAIL_FORWARDS` で指定された転送先にメールが自動転送される

## 制限事項

- SES の制限に準拠
  - メールサイズ制限：SES v2 では MIME エンコード後のサイズで 40MB まで
- 転送メールの送信元アドレスは SES で認証済みである必要あり

## トラブルシューティング

エラーが発生した場合は、CloudWatch Logs で詳細を確認できます。主なエラーケース：

- 環境変数の設定ミス
- IAM 権限の不足
- メールサイズの超過
- SES の制限超過

## ライセンス

このプロジェクトは MIT ライセンスの下で公開されています。詳細は [LICENSE](LICENSE) ファイルを参照してください。

## 貢献

Issue や Pull Request は歓迎します。大きな変更を加える場合は、まず Issue で提案してください。

## 開発環境のセットアップ

### 必要なツール

- Python 3.8以上
- pip
- AWS CLI
- Git

### ローカル開発環境の構築

1. リポジトリのクローン
```bash
git clone https://github.com/t0k6/AWS-Lambda-SES-transfer-email
cd AWS-Lambda-SES-transfer-email
```

2. 仮想環境の作成と依存関係のインストール
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### テストの実行

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## CI/CD パイプライン

GitHub Actionsを使用して以下の自動化を実現しています：

- プルリクエスト時のユニットテスト実行
- AWS Lambda へのアップロード用zipファイルの作成

## テスト

### ユニットテスト

- motoライブラリを使用してAWSサービスをモック化してテスト
- 転送メールのメッセージ処理をテスト
