import React from 'react';
import { BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip } from 'chart.js';
import { Bar } from 'react-chartjs-2';
import { formatHoursMinutes, toChartHours } from './reportStats';

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip);

const BAR_COLOR = 'rgba(34, 197, 94, 0.85)';
const ACCENT_COLOR = '#22C55E';
const AXIS_TEXT_COLOR = '#111827';

function formatHourTick(value) {
  if (value === 0) return '';
  if (Number.isInteger(value)) return `${value}시간`;
  return null;
}

function buildChartData(graph) {
  return {
    labels: graph.map((item) => item.day),
    datasets: [
      {
        label: '학습 시간 (시간)',
        data: graph.map((item) => toChartHours(item.seconds)),
        backgroundColor: BAR_COLOR,
        borderWidth: 0,
        borderRadius: { topLeft: 6, topRight: 6 },
        maxBarThickness: 28,
      },
    ],
  };
}

function buildChartOptions(graph) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(0, 0, 0, 0.9)',
        padding: 10,
        borderColor: ACCENT_COLOR,
        borderWidth: 1,
        callbacks: {
          title: (context) => `${context[0].label}요일`,
          label: (context) => ` ${formatHoursMinutes(graph[context.dataIndex]?.seconds)}`,
          afterLabel: () => '학습 완료',
        },
      },
    },
    scales: {
      y: {
        beginAtZero: true,
        suggestedMax: 1,
        grid: { display: false },
        ticks: {
          color: AXIS_TEXT_COLOR,
          font: { size: 11 },
          stepSize: 1,
          callback: formatHourTick,
        },
      },
      x: {
        grid: { display: false },
        ticks: {
          color: AXIS_TEXT_COLOR,
          font: { size: 12 },
          maxRotation: 0,
          minRotation: 0,
        },
      },
    },
  };
}

export default function WeeklyStudyChart({ graph }) {
  return (
    <div className="mobile-report__chart">
      <Bar data={buildChartData(graph)} options={buildChartOptions(graph)} />
    </div>
  );
}
