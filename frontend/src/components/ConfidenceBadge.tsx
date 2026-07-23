import React from 'react';
import { Tag } from 'antd';

interface ConfidenceBadgeProps {
  value: number;
}

/** 置信度徽标：>=0.8 高(绿)，0.5-0.8 中(橙)，<0.5 低(红) */
const ConfidenceBadge: React.FC<ConfidenceBadgeProps> = ({ value }) => {
  const pct = Math.round(value * 100);
  let color = 'red';
  let label = '低';
  if (value >= 0.8) {
    color = 'green';
    label = '高';
  } else if (value >= 0.5) {
    color = 'orange';
    label = '中';
  }
  return (
    <Tag color={color}>
      {label} · {pct}%
    </Tag>
  );
};

export default ConfidenceBadge;
