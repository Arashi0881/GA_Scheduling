# Xếp thời khóa biểu bằng giải thuật di truyền

Dự án dùng **hai giải thuật di truyền (GA)** để phân công giảng viên theo môn yêu thích và xếp thời khóa biểu. Bài toán có **60 môn, 480 lớp học phần, 960 buổi, 60 giảng viên và 35 phòng**. Mỗi lớp học hai buổi trong tuần, từ thứ Hai đến thứ Sáu, mỗi ngày sáu tiết. [Đề bài](requirement.md)

## Chạy nhanh

Mở terminal tại thư mục gốc của repo. Hai bộ giải trong `src/` chạy bằng **Python 3.10 trở lên** và dùng thư viện chuẩn.

```sh
python -m src.schedule_ga
```

Lệnh đọc ba tệp trong `input/`, dùng **`hybrid` với seed 42** và lưu kết quả vào `results/`. Bộ dữ liệu mẫu đã có giảng viên và ca cho từng lớp, nên lệnh có thể chạy ngay từ bản clone.

| Tệp kết quả | Nội dung |
|---|---|
| `schedule.csv` | Một dòng mỗi buổi, gồm môn, lớp, giảng viên, ngày, tiết, ca, phòng, cỡ lớp và cỡ phòng. |
| `fitness.csv` | Fitness tốt nhất và trung bình, số buổi thiếu phòng, điểm phạt mềm và số lượt chấm theo thế hệ. |
| `run.json` | Chế độ, seed, ngân sách thực dùng, lý do dừng, từng thành phần điểm và lượt đầu tìm được lịch khả thi. |

Nếu hết ngân sách khi còn thiếu phòng, `schedule.csv` vẫn có đủ 960 dòng và đánh dấu các buổi chưa có phòng bằng `UNASSIGNED`. Lệnh trả mã **2**. Lịch đủ phòng trả mã **0**. Dùng `--out` để lưu mỗi lần chạy vào một thư mục riêng.

## Phân công lại rồi xếp lịch

```sh
python -m src.assign_ga --input input --out assigned_input --seed 42
python -m src.schedule_ga --input assigned_input --out results_reassigned --variant flexible --seed 42
```

Bước phân công dùng top 3 trong `professors.csv` và tự chọn **giảng viên cùng số lớp sáng, chiều của mỗi người**. Có thể dùng `input/` để thử vì bộ phân công tính lại cột `professor`. Với dữ liệu tự chuẩn bị, cột này có thể bỏ trống hoặc bỏ hẳn ở bước phân công.

Mỗi giảng viên nhận từ **1 đến 10 lớp mỗi tuần**, tối đa **7 lớp trong một ca**. Mỗi lớp chiếm hai tiết trong ca, còn mỗi ca có 15 tiết mỗi tuần. Các môn xếp hạng 1, 2 và 3 trong danh sách yêu thích lần lượt chịu 0, 1 và 2 điểm phạt. GA giảm tổng điểm và chỉ xét phân công hợp lệ. Kết quả nằm trong `assigned_input/sections.csv`, kèm tải dạy theo ca trong `teaching_load.csv` và lịch sử điểm trong `assignment_history.csv`.

## Dữ liệu đầu vào

| Tệp trong `input/` | Các cột |
|---|---|
| [sections.csv](input/sections.csv) | `course`, `section`, `registration_size`, `professor`, `period`. Cột `professor` cần có khi chạy bộ xếp lịch. |
| [professors.csv](input/professors.csv) | `professor`, `favorite_1`, `favorite_2`, `favorite_3`. Ba mã môn yêu thích phải hợp lệ và phân biệt. |
| [rooms.csv](input/rooms.csv) | `room`, `size`, `closed_day`, `closed_slot`. Hai cột cuối xác định một tiết phòng đóng trong tuần. |

Tiết 1–3 thuộc ca sáng (`AM`), tiết 4–6 thuộc ca chiều (`PM`). Cỡ lớp và phòng dùng các mức 0, 1, 2 tương ứng nhỏ, vừa, lớn. Bộ giải giữ ca của mỗi môn theo dữ liệu đầu vào.

## GA xếp lịch hoạt động như thế nào?

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

Trong các dữ liệu được hỗ trợ, mỗi môn có một ca và mỗi giảng viên có lớp thuộc top 3, nên `C` và `U` bằng 0. Trên bộ mẫu với `hybrid` và seed 42, thế hệ 6 xếp đủ phòng với **P = 364**. Thế hệ 11 đạt **H = 0, P = 360 và fitness ≈ 0,9652509653**.

Cận dưới 360 xuất phát từ tải dạy. Với một giảng viên dạy *n* buổi trong *d* ngày, có *m* ngày dạy cả hai ca, ta có *n* ≤ 3(*d* + *m*). Do *d* ≤ 5 và *n* chẵn, suy ra *n* ≤ 2*d* + 4*m* + 4. Cộng qua 60 giảng viên cho 960 ≤ 2*D* + 4*M* + 240. Vì tổng độ trải tuần *W* ít nhất bằng tổng số ngày dạy *D*, ta có *P* ≥ *W* + 2*M* ≥ 360.

## Mã nguồn và công cụ cục bộ

- [src/assign_ga.py](src/assign_ga.py) phân công lớp theo top 3 và giới hạn tải.
- [src/schedule_ga.py](src/schedule_ga.py) xếp ngày, tiết và phòng rồi xuất kết quả.
- [src/run.py](src/run.py) gọi thêm các công cụ kiểm tra, vẽ biểu đồ và xuất Excel. Lệnh `python -m src.run` cần có `tools/`, `matplotlib` và `openpyxl` tại máy chạy.

Repo lưu mã nguồn, dữ liệu mẫu và tài liệu. Theo [.gitignore](.gitignore), `tools/`, `requirements.txt` và các thư mục kết quả chỉ có trong bản làm việc cục bộ.
