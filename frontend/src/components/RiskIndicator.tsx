import React from 'react';
import { Progress, Tooltip } from 'antd';

interface RiskIndicatorProps {
  value: number;
}

/** 风险指标仪表盘风格展示（0-1） */
const RiskIndicator: React.FC<RiskIndicatorProps> = ({ value }) => {
  const pct = Math.round(value * 100);
  let color: string = '#52c41a';
  let label = '低风险';
  if (value >= 0.8) {
    color = '#ff4d4f';
    label = '极高风险';
  } else if (value >= 0.6) {
    color = '#fa8c16';
    label = '高风险';
  } else if (value >= 0.4) {
    color = '#faad14';
    label = '中风险';
  }

  return (
    <Tooltip title={`${label} · ${pct}%`}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
        <Progress
          type="dashboard"
          percent={pct}
          size={80}
          strokeColor={color}
          format={() => `${pct}%`}
        />
        <span style={{ color, fontSize: 12 }}>{label}</span>
      </div>
    </Tooltip>
  );
};

export default RiskIndicator;
