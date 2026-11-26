# Xếp thời khóa biểu bằng giải thuật di truyền

Dự án phân công giảng viên theo mẫu tải của bộ dữ liệu gốc rồi dùng **giải thuật di truyền (GA)** để xếp thời khóa biểu. Bài toán có **60 môn, 480 lớp học phần, 960 buổi, 60 giảng viên và 35 phòng**. Mỗi lớp học hai buổi trong tuần, từ thứ Hai đến thứ Sáu, mỗi ngày sáu tiết. [Đề bài](requirement.md)

## Chạy nhanh

Mở terminal tại thư mục gốc của repo. Các lệnh trong `src/` chạy bằng **Python 3.10 trở lên** và dùng thư viện chuẩn.

```sh
python -m src.assign --input input --out assigned_input
python -m src.schedule_ga --input assigned_input --out results --variant hybrid --seed 42
```

Lệnh đầu đọc ba CSV trong `input/` và phân công theo mẫu tải gốc. Lệnh sau dùng phương án đó để xếp ngày, tiết và phòng. Với một bộ dữ liệu đã có cột `professor`, có thể chạy riêng bước xếp lịch. Chế độ mặc định của bộ xếp lịch là `hybrid`.

| Tệp kết quả | Nội dung |
|---|---|
| `schedule.csv` | Một dòng mỗi buổi, gồm môn, lớp, giảng viên, ngày, tiết, ca, phòng, cỡ lớp và cỡ phòng. |
| `fitness.csv` | Fitness tốt nhất và trung bình, số buổi thiếu phòng, điểm phạt mềm và số lượt chấm theo thế hệ. |
| `run.json` | Chế độ, seed, ngân sách thực dùng, lý do dừng, từng thành phần điểm và lượt đầu tìm được lịch khả thi. |

Nếu hết ngân sách khi còn thiếu phòng, `schedule.csv` vẫn có đủ 960 dòng và đánh dấu các buổi chưa có phòng bằng `UNASSIGNED`. Lệnh trả mã **2**. Lịch đủ phòng trả mã **0**. Dùng `--out` để lưu mỗi lần chạy vào một thư mục riêng.

## Bước 1 — Phân công theo mẫu của bộ gốc

Bộ gốc gồm **15 nhóm**, mỗi nhóm có bốn giảng viên, hai môn sáng và hai môn chiều. Mỗi môn có tám lớp, chia cho hai người theo tỷ lệ 7–1 hoặc 6–2. Các giảng viên trong một nhóm có bốn tải dạy như sau.

| Vai trò | Lớp sáng | Lớp chiều |
|---|---:|---:|
| Chỉ dạy sáng | 7 | 0 |
| Chỉ dạy chiều | 0 | 7 |
| Dạy chủ yếu buổi sáng | 6 | 3 |
| Dạy chủ yếu buổi chiều | 3 | 6 |

`src.assign` liệt kê các nhóm phù hợp với top 3 và ca học, sau đó dùng quay lui để chọn 15 nhóm bao phủ toàn bộ môn và giảng viên. Mỗi giảng viên nhận 14 hoặc 18 buổi một tuần. Lệnh báo lỗi nếu top 3 và ca học hiện có không cho phép lập đủ nhóm.

Kết quả nằm trong `assigned_input/sections.csv`. `assignment_blocks.csv` ghi cách chia lớp của từng môn theo nhóm, còn `teaching_load.csv` ghi tải dạy theo ca. GA bắt đầu chạy ở bước 2.

## Dữ liệu đầu vào

| Tệp trong `input/` | Các cột |
|---|---|
| [sections.csv](input/sections.csv) | `course`, `section`, `registration_size`, `professor`, `period`. Cột `professor` do bước phân công tạo ra và cần có khi xếp lịch. |
| [professors.csv](input/professors.csv) | `professor`, `favorite_1`, `favorite_2`, `favorite_3`. Ba mã môn yêu thích phải hợp lệ và phân biệt. |
| [rooms.csv](input/rooms.csv) | `room`, `size`, `closed_day`, `closed_slot`. Hai cột cuối xác định một tiết phòng đóng trong tuần. |

Tiết 1–3 thuộc ca sáng (`AM`), tiết 4–6 thuộc ca chiều (`PM`). Cỡ lớp và phòng dùng các mức 0, 1, 2 tương ứng nhỏ, vừa, lớn. Bộ giải giữ ca của mỗi môn theo dữ liệu đầu vào.

## Bước 2 — Xếp thời khóa biểu

Một cá thể gồm **60 gene**, mỗi gene chứa lịch tuần của một giảng viên. Hai buổi của một lớp phải đúng ca, cách nhau ít nhất hai ngày và tránh trùng tiết với các lớp khác của cùng giảng viên. GA khởi tạo 28 cá thể, giữ hai cá thể tốt nhất, chọn cha mẹ theo nhóm ba ứng viên và lai ghép theo nguyên gene. Khi xuất lịch, bộ giải xét lớp lớn trước rồi lấy phòng đang mở nhỏ nhất đủ cỡ.

| Chế độ | Cách tìm kiếm | Giới hạn mặc định |
|---|---|---:|
| `plain` | GA dùng chọn lọc, lai ghép và đột biến. | 450 thế hệ |
| `hybrid` | Thêm tìm kiếm cục bộ sau lai ghép. | 450 thế hệ |
| `flexible` | Thêm phép dời buổi sang thời điểm hợp lệ, có thể chấp nhận thêm tiết trống để giảm thiếu phòng. | 200.000 lượt chấm |

Dùng `--generations N` hoặc `--max-evaluations N` để đổi giới hạn. Lượt chấm bao gồm các phương án tìm kiếm cục bộ thực sự được tính fitness. Bộ giải dừng khi hết ngân sách hoặc khi xếp đủ phòng và đạt cận dưới của điểm mềm.

## Fitness và kết quả mẫu

Bộ giải tối đa hóa **F = 1 / (1 + H + P/10.000)**. `H` là số buổi thiếu phòng. Hai lịch có cùng `H` được ưu tiên theo điểm phạt mềm `P` thấp hơn.

**P = G + W + 2M + C + R + U**

| Ký hiệu | Cách tính |
|---|---|
| `G` | Tổng tiết trống giữa tiết đầu và cuối của mỗi giảng viên trong mỗi ngày. |
| `W` | Tổng độ dài từ ngày dạy đầu đến ngày dạy cuối của mỗi giảng viên, tính cả hai đầu. |
| `M` | Số ngày giảng viên dạy cả hai ca, cộng qua mọi giảng viên. |
| `C` | Với từng môn, lấy số buổi của ca có ít buổi hơn rồi cộng qua các môn. |
| `R` | Tổng chênh lệch cỡ phòng và cỡ lớp ở các buổi có phòng. |
| `U` | Số giảng viên chưa được giao lớp thuộc môn yêu thích. |

Trong các dữ liệu được hỗ trợ, mỗi môn có một ca và mỗi giảng viên có lớp thuộc top 3, nên `C` và `U` bằng 0. Trên `input/` hiện tại, sau khi phân công theo mẫu gốc, `hybrid` với seed 42 xếp đủ phòng ở thế hệ 2 và đạt **H = 0, P = 360, fitness ≈ 0,9652509653** ở thế hệ 16.

Cận dưới 360 xuất phát từ tải dạy. Với một giảng viên dạy *n* buổi trong *d* ngày, có *m* ngày dạy cả hai ca, ta có *n* ≤ 3(*d* + *m*). Do *d* ≤ 5 và *n* chẵn, suy ra *n* ≤ 2*d* + 4*m* + 4. Cộng qua 60 giảng viên cho 960 ≤ 2*D* + 4*M* + 240. Vì tổng độ trải tuần *W* ít nhất bằng tổng số ngày dạy *D*, ta có *P* ≥ *W* + 2*M* ≥ 360.

## Mã nguồn và công cụ cục bộ

- [src/assign.py](src/assign.py) phân công lớp theo top 3 và mẫu tải gốc.
- [src/schedule_ga.py](src/schedule_ga.py) xếp ngày, tiết và phòng rồi xuất kết quả.
- [src/run.py](src/run.py) gọi thêm các công cụ kiểm tra, vẽ biểu đồ và xuất Excel. Lệnh `python -m src.run` cần có `tools/`, `matplotlib` và `openpyxl` tại máy chạy.

Repo lưu mã nguồn, dữ liệu mẫu và tài liệu. Theo [.gitignore](.gitignore), `tools/`, `requirements.txt` và các thư mục kết quả chỉ có trong bản làm việc cục bộ.
