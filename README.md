# Messenger Call Keeper

Dashboard quản trị gọn cho một tiến trình browser Messenger trên Linux. Mục tiêu là cung cấp browser profile bền, theo dõi tài nguyên và phục hồi tiến trình; **không cam kết Messenger duy trì cuộc gọi vô thời hạn**.

## Trạng thái

Đã có nền backend FastAPI, đăng nhập admin Argon2id, session cookie có CSRF, giới hạn đăng nhập, dashboard responsive, số liệu host qua `psutil`, SQLite cho lịch sử/sự kiện/cấu hình, browser lifecycle manager và các script systemd.

Call Manager cố ý trả `unverified`; ứng dụng hiện không đọc được trạng thái đăng nhập Messenger hoặc WebRTC một cách đáng tin cậy. Không hiển thị `Connected` dựa trên việc browser đang chạy. Messenger có thể đổi giao diện, giới hạn tài khoản hoặc ngắt cuộc gọi; mọi luồng phục hồi đều cần kiểm chứng thủ công.

## Phát triển trong Codespaces

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
export ADMIN_PASSWORD_HASH="$(python -m backend.security hash-password)"
export SESSION_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export SESSION_HTTPS_ONLY=false
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Lệnh hash hỏi mật khẩu hai lần, yêu cầu tối thiểu 12 ký tự và chỉ in Argon2id hash. Mở port 8000 trong Codespaces. SQLite và browser profile cục bộ được tạo dưới `data/` và không đưa vào Git.

Chạy test:

```bash
python -m pytest -q
```

Codespaces phù hợp để kiểm tra API, session, CSRF, UI và số liệu container. Nó không chứng minh được cuộc gọi thật, thiết bị âm thanh, chất lượng WebRTC, độ bền 24/7 hoặc mức RAM trên VPS 1 GB. Có thể không có browser/X display cài sẵn; không tự động vượt CAPTCHA, 2FA hay cơ chế bảo vệ tài khoản.

## Cài trên VPS

Hỗ trợ Debian 13 và Ubuntu 24.04 trên `x86_64`/`aarch64`. Clone repository rồi chạy:

```bash
sudo bash scripts/setup.sh
```

Script cài Python, Firefox ESR, Xvfb và các gói GUI login tùy chọn; tạo user hệ thống `messenger-call-keeper`, virtualenv, cấu hình quyền và khởi động systemd. Ubuntu dùng repository APT chính thức của Mozilla cho Firefox ESR. Admin password được nhập tương tác và lưu dưới dạng Argon2id hash; session secret được tạo ngẫu nhiên. Service chỉ bind `127.0.0.1:8000`.

Đặt reverse proxy HTTPS phía trước trước khi truy cập từ xa. Không mở trực tiếp port 8000, VNC 5900 hoặc noVNC 6080 ra Internet. Cookie `Secure` được bật trong cấu hình VPS.

Để đăng nhập Messenger lần đầu, tùy chọn GUI chỉ chạy khi được yêu cầu:

```bash
sudo bash scripts/gui-login.sh start
ssh -N -L 6080:127.0.0.1:6080 USER@VPS
```

Sau khi tạo SSH tunnel, mở `http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale&path=websockify` trên máy cá nhân. Đăng nhập thủ công qua noVNC rồi dừng GUI bằng `sudo bash scripts/gui-login.sh stop`. Cả hai listener chỉ bind loopback; không cấu hình reverse proxy công khai cho chúng.

Cập nhật tạo backup cấu hình, database và browser profile trước khi thay code:

```bash
sudo bash scripts/deploy.sh
```

Gỡ phần mềm nhưng giữ profile/database mặc định:

```bash
sudo bash scripts/uninstall.sh
```

Chỉ dùng `sudo bash scripts/uninstall.sh --purge` khi chủ động xóa cả dữ liệu và cấu hình. Các script không tự xóa profile khi cập nhật.

## Cấu hình và API

`systemd/messenger-call-keeper.service` chạy backend bằng user riêng, tự khởi động lại backend khi lỗi và không mở cổng công khai. `messenger-call-keeper-xvfb.service` cung cấp display ảo. Tệp `.env.example` liệt kê biến môi trường; không điền secret vào Git. Sau lần bootstrap, hash admin hiện tại nằm trong bảng riêng của SQLite file quyền `0600`; API đổi mật khẩu sẽ làm session cũ mất hiệu lực.

API quản trị gồm `GET /api/system`, `/api/system/history`, `/api/browser/status`, `/api/call/status`, `/api/logs`, `/api/settings`; điều khiển browser qua `POST /api/browser/start` và `/api/browser/stop`. Settings dùng `PUT /api/settings`; đổi mật khẩu dùng `POST /api/auth/change-password`. Mọi route quản trị yêu cầu session; các thao tác thay đổi yêu cầu `X-CSRF-Token`. `/api/health` chỉ trả trạng thái sống tối thiểu.

Browser executable được giới hạn trong Firefox ESR, Firefox và Chromium; không có API chạy shell tùy ý. Profile nằm riêng và chứa cookie đăng nhập, cần bảo vệ như thông tin xác thực. Browser manager không ghi cookie/token vào log. Browser có thể tốn nhiều RAM hơn mức VPS 1 GB cho phép; dùng dashboard đo RSS thực tế trước khi cân nhắc chạy liên tục.

Chế độ mặc định Eco lấy mẫu lịch sử mỗi 60 giây; Balanced mỗi 30 giây; Performance mỗi 15 giây. Các chế độ này chỉ đổi tần suất lấy mẫu, không tự ý tắt daemon, sửa kernel, tạo swap hoặc xóa cache/profile. Lịch sử SQLite được giới hạn theo ngày và số bản ghi. Dashboard đọc network throughput, zombie process và bộ đếm OOM Linux; nhiệt độ CPU chỉ hiển thị nếu kernel/container cung cấp cảm biến. Chưa ghi sự kiện reboot.

## Kiểm thử và giới hạn

Test suite hiện kiểm tra đăng nhập, rate limit, CSRF, vô hiệu hóa session khi đổi mật khẩu, bảo vệ API, cấu hình allowlist, SQLite và trạng thái cuộc gọi không xác minh. Các test không chạy trên Debian/Ubuntu VPS thật. Browser chưa được benchmark trên cấu hình 1 GB và khả năng tham gia/duy trì Messenger Call chưa được kiểm chứng; đây là điều kiện bắt buộc trước khi xem hệ thống đủ ổn định để chạy sản xuất.

Không có cam kết Messenger/WebRTC tương thích lâu dài. Tự động restart browser chỉ khôi phục tiến trình, không tự khẳng định đã đăng nhập lại hoặc đã vào lại cuộc gọi.
