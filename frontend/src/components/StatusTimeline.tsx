import React from 'react';
import { Timeline } from 'antd';

export interface StatusTimelineItem {
  status: string;
  time: string;
  description?: string;
}

interface StatusTimelineProps {
  items: StatusTimelineItem[];
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'gray',
  approved: 'blue',
  queued: 'blue',
  submitted: 'processing',
  partial_fill: 'orange',
  filled: 'green',
  blocked: 'red',
  rejected: 'red',
  cancelled: 'gray',
  draft: 'gray',
  confirmed: 'green',
  active: 'green',
  paused: 'orange',
  revoked: 'red',
};

const StatusTimeline: React.FC<StatusTimelineProps> = ({ items }) => {
  return (
    <Timeline
      items={items.map((item) => ({
        color: STATUS_COLOR[item.status] ?? 'blue',
        children: (
          <div>
            <div style={{ fontWeight: 500 }}>{item.status}</div>
            {item.description && (
              <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>{item.description}</div>
            )}
            <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>{item.time}</div>
          </div>
        ),
      }))}
    />
  );
};

export default StatusTimeline;
