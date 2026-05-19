import React from 'react';
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    BarElement,
    Title,
    Tooltip,
    Legend,
} from 'chart.js';
import { Bar } from 'react-chartjs-2';

// ✅ Chart.js 필수 구성 요소 등록
ChartJS.register(
    CategoryScale,
    LinearScale,
    BarElement,
    Title,
    Tooltip,
    Legend
);

// ✅ 빨간점 위치(Y축 라벨 아래, X축 라벨보다 더 아래쪽)에 텍스트를 그리는 커스텀 플러그인
const cornerTextPlugin = {
    id: 'cornerText',
    afterDraw(chart) {
        const { ctx, chartArea: { left, bottom } } = chart;
        ctx.save();
        ctx.font = 'bold 12px sans-serif';
        ctx.fillStyle = '#000000';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        // left - 20: Y축 '0' 라벨의 가로 중앙 위치
        // bottom + 22: X축 요일 라벨 아래쪽 빨간 점 세로 위치
        ctx.fillText('시간/요일', left - 20, bottom + 22);
        ctx.restore();
    }
};

export default function StudyChart({ rawData }) {
    const normalizedData = Array.isArray(rawData)
        ? rawData
        : rawData?.data || [];

    const labels = normalizedData.map(item => item.day || '');
    const values = normalizedData.map(item => Number(item?.minutes ?? 0));
    const hasData = values.some(value => value > 0);

    // ✅ 가공 로직: 백엔드 데이터를 Chart.js 형식으로 변환
    const data = {
        labels,
        datasets: [
            {
                label: '학습 시간 (시간)',
                data: values.map(m => {
                    const hours = m / 60;
                    // 짧은 학습 시간이라도 그래프에 최소한으로 표시될 수 있도록 보장 (약 1.8분 미만인 경우 최소 0.03시간으로 강제 설정)
                    if (hours > 0 && hours < 0.03) {
                        return 0.03;
                    }
                    return Number(hours.toFixed(4));
                }),
                backgroundColor: 'rgba(74, 222, 128, 0.85)',
                borderColor: '#4ade80',
                borderWidth: 0,
                borderRadius: {
                    topLeft: 6,
                    topRight: 6,
                },
            },
        ],
    };

    const options = {
        layout: {
            padding: {
                left: 20, // 왼쪽 텍스트('시간')가 잘리지 않도록 캔버스 여백 확보
                bottom: 20, // 아래쪽 빨간점 위치까지 텍스트가 내려갈 수 있도록 여백 확보
            }
        },
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: 'rgba(0, 0, 0, 0.9)',
                padding: 12,
                borderRadius: 8,
                titleColor: '#fff',
                bodyColor: '#fff',
                borderColor: '#4ade80',
                borderWidth: 1,
                boxPadding: 8,
                usePointStyle: false,
                callbacks: {
                    title: (context) => context[0].label + '요일',
                    label: (context) => {
                        const dataItem = rawData[context.dataIndex] || {};
                        const totalSeconds = dataItem.seconds !== undefined 
                            ? Number(dataItem.seconds) 
                            : Number(dataItem.minutes || 0) * 60;
                        
                        const h = Math.floor(totalSeconds / 3600);
                        const m = Math.floor((totalSeconds % 3600) / 60);
                        const s = Math.floor(totalSeconds % 60);
                        const parts = [];

                        if (h > 0) parts.push(`${h}시간`);
                        if (m > 0 || parts.length === 0) parts.push(`${m}분`);

                        return ` ${parts.join(' ')}`;
                    },
                    afterLabel: () => '학습 완료',
                },
            },
        },
        scales: {
            y: {
                beginAtZero: true,
                title: {
                    display: false,
                    text: '시간',
                    font: { size: 12, weight: 'bold' },
                    color: '#000000',
                    rotation: 0,
                    padding: 8,
                },
                grid: {
                    display: false,
                },
                suggestedMax: 1,
                ticks: {
                    color: '#000000',
                    font: { size: 12, weight: 500 },
                    padding: 8,
                    stepSize: 1,
                    callback: function(value) {
                        if (value === 0) return ''; // 0시간 텍스트 제거
                        if (Number.isInteger(value)) {
                            return value + '시간';
                        }
                        return null; // 소수점 단위 숨김
                    }
                },
            },
            x: {
                title: {
                    display: false,
                },
                grid: {
                    display: false,
                },
                ticks: {
                    color: '#000000',
                    font: { size: 12, weight: 500 },
                    maxRotation: 0,
                    minRotation: 0,
                    padding: 8,
                },
            },
        },
    };

    if (!normalizedData.length || !hasData) {
        return (
            <div style={{
                height: '350px',
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-text-muted)',
                fontSize: '14px',
            }}>
                주간 학습 기록이 없습니다.
            </div>
        );
    }

    return (
        <div style={{
            height: '350px',
            width: '100%',
            padding: '10px 0',
        }}>
            <Bar data={data} options={options} plugins={[cornerTextPlugin]} />
        </div>
    );
}