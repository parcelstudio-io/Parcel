# Scrum folders

Layout: `scrum/YYYYMMDD/task_<n>/` — one folder per sprint, `task_<n>`
monotonically increasing **within the date**, because there can be more than
one sprint in a day. Never write cards directly under the date folder.

Each `task_<n>/` contains a `README.md` (board, model assignments, working
agreements, definition of done, handoffs) plus one file per workstream with
the task cards. The working-agreement template to inherit is
[20260804/task_1/README.md](20260804/task_1/README.md).

Sprint folders are historical records: once a sprint ends they stop being
updated. Anything unfinished or unverified moves to
[../backlog/](../backlog/) — that register outlives every sprint.
