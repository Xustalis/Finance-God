import React from 'react';
import { Card, List, Tag, Empty, Divider } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, WarningOutlined } from '@ant-design/icons';
import type { ConstraintReport as ConstraintReportType } from '../types';

interface ConstraintReportProps {
  report: ConstraintReportType;
}

/** 约束校验报告：通过/失败/警告 */
const ConstraintReport: React.FC<ConstraintReportProps> = ({ report }) => {
  const passed = report.passed ?? [];
  const failed = report.failed ?? [];
  const warnings = report.warnings ?? [];

  if (passed.length === 0 && failed.length === 0 && warnings.length === 0) {
    return <Empty description="暂无约束校验数据" />;
  }

  return (
    <Card size="small" title="约束校验报告">
      {failed.length > 0 && (
        <>
          <div style={{ marginBottom: 8, color: '#ff4d4f', fontWeight: 500 }}>
            <CloseCircleOutlined /> 失败 ({failed.length})
          </div>
          <List
            size="small"
            dataSource={failed}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta
                  title={<Tag color="red">{item.rule}</Tag>}
                  description={item.explanation ?? `值 ${item.value} 超过限制 ${item.limit}`}
                />
              </List.Item>
            )}
          />
        </>
      )}

      {warnings.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <div style={{ marginBottom: 8, color: '#faad14', fontWeight: 500 }}>
            <WarningOutlined /> 警告 ({warnings.length})
          </div>
          <List
            size="small"
            dataSource={warnings}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta
                  title={<Tag color="orange">{item.rule}</Tag>}
                  description={item.note ?? `值 ${item.value}，限制 ${item.limit}`}
                />
              </List.Item>
            )}
          />
        </>
      )}

      {passed.length > 0 && (
        <>
          <Divider style={{ margin: '12px 0' }} />
          <div style={{ marginBottom: 8, color: '#52c41a', fontWeight: 500 }}>
            <CheckCircleOutlined /> 通过 ({passed.length})
          </div>
          <List
            size="small"
            dataSource={passed}
            renderItem={(item) => (
              <List.Item>
                <List.Item.Meta
                  title={<Tag color="green">{item.rule}</Tag>}
                  description={item.note ?? `值 ${item.value}，限制 ${item.limit}`}
                />
              </List.Item>
            )}
          />
        </>
      )}
    </Card>
  );
};

export default ConstraintReport;
