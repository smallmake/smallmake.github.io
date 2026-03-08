#!/usr/local/bin/ruby

require 'nkf'
require 'cgi'
require 'json'
require 'csv'
require 'fileutils'
require 'net/http' # ★ 追加: reCAPTCHA APIとの通信に必要

cgi = CGI.new

# sendmailのパス
SENDMAIL = '/usr/sbin/sendmail'
# 管理者メールアドレス
ADMIN_MAIL = 'webmaster@smallmake.sakura.ne.jp' # webmaster@smallmake.sakura.ne.jp に nakai@smallmake.comへの転送を設定すること

data_dir  = '/home/smallmake/www/data'


# reCAPTCHAの設定
recaptcha_secret_path = File.join(data_dir, 'recaptcha.secret')
RECAPTCHA_SECRET_KEY =
  begin
    path = File.expand_path(recaptcha_secret_path)
    File.read(path, mode: 'rb').strip
  rescue
    ''
  end

RECAPTCHA_URL = 'https://www.google.com/recaptcha/api/siteverify'



# フォームからの入力を取得
email   = cgi['email'].strip
pname   = cgi['pname'].strip
subject = cgi['subject'].strip.empty? ? "問い合わせ" : cgi['subject'].strip
body    = cgi['body'].strip
recaptcha_response = cgi['g-recaptcha-response'] # ★ 追加: CAPTCHA応答トークンを取得

# REMOTE_ADDR / User-Agent / Referer を取得
remote_ip = (ENV['REMOTE_ADDR'] || '').strip
user_agent  = (ENV['HTTP_USER_AGENT'] || '').strip
referer     = (ENV['HTTP_REFERER']    || '').strip

# === reCAPTCHAの検証ロジック ===
def verify_recaptcha(response_token, secret_key, remote_ip)
  uri = URI.parse(RECAPTCHA_URL)
  params = {
    secret: secret_key,
    response: response_token,
    remoteip: remote_ip
  }
  
  # POSTリクエストを作成
  res = Net::HTTP.post_form(uri, params)
  
  # レスポンスをJSONとしてパース
  json_response = JSON.parse(res.body)
  
  # 'success'がtrueなら検証成功
  return json_response['success']
rescue => e
  # 通信エラーなどが発生した場合、安全のために検証失敗と見なす
  puts "reCAPTCHA verification error: #{e.message}"
  return false
end

# CAPTCHAの検証を実行
is_human = verify_recaptcha(recaptcha_response, RECAPTCHA_SECRET_KEY, remote_ip)

unless is_human
  # 検証失敗時の処理: エラーを返してメール送信・CSV書き込みを中止
  print "Status: 400 Bad Request\n"
  print "Content-Type: application/json\n\n"
  puts JSON.generate({ success: false, message: "CAPTCHA verification failed. You may be a bot." })
  exit # ★ スクリプトをここで終了
end

# 送信本文を指定のフォーマットで構築
composed_body = <<~MSG
  MAIL: #{email}
  NAME: #{pname}
  TITLE: #{subject}
  REMOTE-IP: #{remote_ip}
  USER-AGENT: #{user_agent}
  REFERER: #{referer}
  BODY:
  #{body}
MSG

# === CSV出力（先頭に追加） ===
csv_path = File.join(data_dir, 'contact.csv')
timestamp = Time.now.strftime('%Y-%m-%d %H:%M:%S %z')
csv_row = [timestamp, email, pname, subject, body, remote_ip, user_agent, referer]
csv_line = CSV.generate_line(csv_row, force_quotes: true, row_sep: "\n")

begin
  FileUtils.mkdir_p(csv_dir)
  bom = "\uFEFF"
  if File.exist?(csv_path)
    tmp = csv_path + '.tmp'
    File.open(tmp, 'wb') do |fo|
      fo.write(bom)
      fo.write(csv_line)
      File.open(csv_path, 'rb') { |fi| IO.copy_stream(fi, fo) }
    end
    FileUtils.mv(tmp, csv_path)
  else
    File.open(csv_path, 'wb') { |f| f.write(bom + csv_line) }
  end
rescue => e
  # CSVの書き込みエラーはメール送信を妨げないように握りつぶす
end
# === /CSV出力 ===

set = {
  from: email,
  from_name: pname,
  to: ADMIN_MAIL,
  to_name: 'webmaster-smallmake',
  sub: subject,
  body: composed_body  # ← ここで組み立てた本文を使う
}

if set.key?(:from_name)
  set[:from] = NKF.nkf('-jM', set[:from_name]) << '<' << set[:from] << '>'
end

if set.key?(:to_name)
  set[:to] = NKF.nkf('-jM', set[:to_name]) << '<' << set[:to] << '>'
end

begin
  IO.popen("#{SENDMAIL} -t", 'w') do |p|
    p.print "From: #{set[:from]}\n"
    p.print "To: #{set[:to]}\n"
    p.print "Subject: [SMALLMAKE]#{NKF.nkf('-jM', set[:sub])}\n"
    p.print "Reply-To: #{email}\n"  # 返信しやすいように（任意）
    p.print "Content-Transfer-Encoding: 7bit\n"
    p.print "MIME-Version: 1.0\n"
    p.print "Content-Type: text/plain; charset=\"iso-2022-jp\"\n\n"
    p.print NKF.nkf('-j', set[:body])
  end
  print "Status: 200 OK\n"
  print "Content-Type: application/json\n\n"
  puts JSON.generate({ success: true, message: "Send completely" })
rescue => e
  print "Status: 500 Error\n"
  print "Content-Type: application/json\n\n"
  puts JSON.generate({ success: false, message: "Send failed Error: #{e.message}" })
end