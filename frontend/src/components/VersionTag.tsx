import React from 'react';
import { Tag } from 'antd';
import { Tooltip } from 'antd';
import dayjs from 'dayjs';
import { HistoryOutlined } from '@ant-design/icons';

interface VersionTagProps {
  version: number;
  timestamp?: string;
}

/** 版本标签，鼠标悬浮显示时间戳 */
const VersionTag: React.FC<VersionTagProps> = ({ version, timestamp }) => {
  const tip = timestamp ? dayjs(timestamp).format('YYYY-MM-DD HH:mm:ss') : '';
  return (
    <Tooltip title={tip ? `版本 ${version} · ${tip}` : `版本 ${version}`}>
      <Tag icon={<HistoryOutlined />} color="blue">
        v{version}
      </Tag>
    </Tooltip>
  );
};

export default VersionTag;
