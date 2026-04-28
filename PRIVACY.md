# Data Handling Policy — MVP v1

> **Phạm vi:** Tài liệu này áp dụng cho bản MVP demo của DermAssist VN
> (Surface A — Modal + Vercel + Supabase). Khi triển khai trên bệnh viện
> (Surface B), chính sách sẽ được cập nhật để tuân thủ Luật Khám chữa bệnh
> và Nghị định 13/2023/NĐ-CP.

---

## Dữ liệu được lưu

Trong phạm vi MVP, hệ thống lưu:

- **Tài khoản người dùng** (`users`): username, password hash (bcrypt),
  full_name, role, timestamps. Không có email, không có thông tin liên hệ.
- **Encounter** (`encounters`):
  - Đường dẫn ảnh (image_path) + SHA-256 hash của ảnh
  - Kích thước ảnh (width × height × bytes)
  - **Clinical note đã qua PII redaction** (số token đã redact được lưu lại)
  - Kết quả preflight (blur score, brightness, pass/fail)
  - Output AI dưới dạng JSON (chẩn đoán chính, differential, tier, red flags)
  - Chẩn đoán cuối cùng của bác sĩ (tùy chọn — Risk E)
- **Audit log** (`audit_log`): event_type, timestamp, model_version,
  prompt_version, RAG chunk IDs, image SHA-256, output SHA-256, latency,
  token counts. Phục vụ reproducibility và rollback.
- **Knowledge base** (`kb_chunks`): các đoạn từ Quyết định 4416/QĐ-BYT
  (tài liệu công khai từ Bộ Y Tế).

## Dữ liệu KHÔNG được lưu

Hệ thống **không bao giờ** lưu:

- **Họ tên đầy đủ bệnh nhân** — tự động redact bằng regex/spaCy `vi`
  trước khi persist (REQ-SAF-006, REQ-DATA-002).
- **Số CMND/CCCD** — redact.
- **Số điện thoại** — redact.
- **Địa chỉ chi tiết** — redact.
- **Ảnh dưới dạng blob trong DB** — chỉ lưu đường dẫn và SHA-256 hash
  (REQ-DATA-005).
- **Clinical note ở dạng raw (chưa redact)** — chỉ phiên bản đã redact
  được persist; số token đã redact được ghi lại trong audit.
- **PII bệnh nhân thực** — bản MVP chỉ dùng ảnh từ datasets công khai,
  không có ảnh bệnh nhân thực.

Khi guardrail-IN phát hiện và redact PII, sự kiện `pii_redacted` được
ghi vào `audit_log` với số lượng token đã redact (không phải nội dung
gốc).

## Retention

- **Encounter:** tự động hết hạn sau **90 ngày** kể từ khi tạo
  (REQ-DATA-001). Một cron job chạy hằng đêm xóa các bản ghi đã hết hạn.
- **Manual delete:** Người dùng có thể xóa bất kỳ encounter nào của
  mình trước thời hạn (REQ-FUNC-012). Việc xóa cascade sang file ảnh
  và đặt audit_log.encounter_id = NULL (giữ lại audit, gỡ ràng buộc).
- **Audit log:** giữ lại lâu hơn encounter để phục vụ truy vết, không
  chứa PII (đã được redact ở tầng input).
- **Backup:** Supabase free tier tự động snapshot hằng ngày
  (REQ-DATA-006). Snapshot tuân theo cùng chính sách retention 90 ngày.

## Trong phạm vi MVP

- Hệ thống MVP **không xử lý ảnh hoặc dữ liệu bệnh nhân thực**.
- Mọi ảnh trong demo là ảnh mẫu từ các datasets công khai
  (Fitzpatrick17k, ISIC, DermNet NZ) hoặc ảnh tự tạo cho mục đích thử
  nghiệm.
- Banner đỏ "DEMO ONLY — Sample images only. NOT for clinical use"
  hiển thị trên mọi trang (REQ-SAF-003).
- Tài khoản demo (`demo / demo`) bị giới hạn 10 yêu cầu/phút
  (REQ-FUNC-013).
- Đây là **bản triển khai tham khảo Apache 2.0 cho mục đích nghiên cứu /
  luận văn / portfolio**, không phải sản phẩm lâm sàng.
- Khi có hợp tác bệnh viện và phê duyệt IRB, hệ thống sẽ chuyển sang
  Surface B với chính sách dữ liệu đầy đủ — xem
  [docs/path-to-production.md](docs/path-to-production.md).
