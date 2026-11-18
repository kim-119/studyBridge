#!/usr/bin/env bash
set -euo pipefail

TARGET="frontend/src/pages/Dashboard.jsx"

if grep -q "PlannerWorkspace" "$TARGET"; then
  echo "ERROR: Dashboard.jsx must not import or render PlannerWorkspace."
  echo "Use /planner, /study-report, /weekly-schedule dedicated routes instead."
  exit 1
fi

if grep -q "학습리포트.*주간일정.*플래너\|activeTab.*planner\|activeTab.*schedule\|activeTab.*report" "$TARGET"; then
  echo "ERROR: Dashboard.jsx contains tab workspace logic."
  echo "Main dashboard must not be replaced by study-report/weekly-schedule/planner tabs."
  exit 1
fi

echo "Dashboard guard passed."
