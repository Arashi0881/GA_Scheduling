num_courses = 60
num_sections = 480 (8 sections per course) 
num_sessions = 960 (2 sessions per section).
course_name = {c01-c60}
num_professors = 60 (namely p01-p60)
num_days = 5 (2-6 or M-T-W-R-F)
num_timeslots_per_day = 6 (timeslot 1, 2, … , 6. Each timeslot is equivalent to 1 session)
num_rooms = 35
room_name = {rm01-rm35}
room_size = {0, 1, 2} (3 types only: 0 for Small rooms, 1 for Average rooms, 2 for Large rooms)
section_registration_size = {0, 1, 2} (corresponding to room_size) 
Constraints:
1. Room/Section: room of size 2 can be used for section_registration_size of size 0 or 1 or 2,
room of size 1 can be used for section_registration_size of size 0 or 1, room of size 0 can ONLY be used for section_registration_size of size 0.
2. A class has 2 sessions (lectures) per week (for example Monday and Thursday), NOT
on the same or adjacent days. For example: a course is scheduled on Monday and Tuesday (next day) is not acceptable. a course scheduled on Monday morning and Monday afternoon is not
acceptable.
3. A professor cannot teach two courses at the same time. No professor can teach more than 20sessions.
4. Classes are scheduled only in available classrooms.
5. A section cannot be scheduled in two different rooms simultaneously.
6. A room cannot be assigned to two different sections at the same time.
Soft constraints:
1. Schedules for professors should not scatter throughout the day or the week. For example, a
professor should NOT have one section in timeslot 1 and another section timeslot 6 on Monday, i.e. he has no classes scheduled during timeslot 2-3-4-5.
2. Schedules for professors should be morning only or afternoon only during a specific day
3. Class sessions for a course should be scheduled in the mornings only or afternoons only.
4. Room size and section registration size should match as much as possible.
Bonus:
1. A professor can list their top 3 favorite courses. Scheduling should use this information to
optimize scheduling so that each professor can have at least 1 favorite class.
2. A professor might NOT teach courses that are NOT in his list.
3. You might add other constraints.
Note:
1. You might need to initialize room sizes, registration, … with random values
2. A course can have different sections. Each section has 2 sessions on 2 different days.
1 session = 1 timeslot. For example: course 1 - section 01 is scheduled for 2 sessions (one on
Monday, another on Wednesday), ALSO another course 1 - section 02 is scheduled for 2
sessions (one on Tuesday, another on Thursday).
Task:
Use Genetic algorithm, create optimal schedule(s) that meet the constraints with minimal
conflicts among sections, rooms, … What’s the fitness function? Show a final class
schedule and the fitness plot.