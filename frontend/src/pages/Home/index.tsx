import React, { useEffect } from 'react';
import { Card, Row, Col, Progress, Statistic, List, Timeline, Tag, Badge, Spin, Empty, Typography } from 'antd';
import {
  AlertOutlined,
  HeartOutlined,
  FundOutlined,
  GlobalOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import useAppStore from '../stores/appStore';
import type { DashboardData } from '../types';

const { Title } = Typography;

const stateColor = (level: number): string => {
  if (level >= 0.7) return '#ff4d4f';
  if (level >= 0.4) return '#faad14';
  return '#52c41a';
};

const Home: React.FC = () => {
  const { dashboardData, loading, fetchDashboard } = useAppStore();

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  if (loading && !dashboardData) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  const data: DashboardData = dashboardData ?? {};
  const mental = data.mental_state;
  const portfolio = data.portfolio_state;
  const market = data.market_sentiment;
  const risk = data.risk_alert;
  const pending = data.pending_items ?? [];
  const activities = data.recent_activities ?? [];

  return (
    <div>
      <Title level={4}>投资仪表盘</Title>

      <Row gutter={[16, 16]}>
        {/* 心智状态 */}
        <Col xs={24} sm={12}>
          <Card title={<><HeartOutlined /> 心智状态</>} bordered={false}>
            {mental ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div>
                  <div style={{ marginBottom: 4 }}>焦虑水平</div>
                  <Progress
                    percent={Math.round((mental.anxiety_level ?? 0) * 100)}
                    strokeColor={stateColor(mental.anxiety_level ?? 0)}
                  />
                </div>
                <div>
                  <div style={{ marginBottom: 4 }}>贪婪水平</div>
                  <Progress
                    percent={Math.round((mental.greed_level ?? 0) * 100)}
                    strokeColor={stateColor(mental.greed_level ?? 0)}
                  />
                </div>
                <div>
                  <div style={{ marginBottom: 4 }}>冲动性</div>
                  <Progress
                    percent={Math.round((mental.impulsivity ?? 0) * 100)}
                    strokeColor={stateColor(mental.impulsivity ?? 0)}
                  />
                </div>
                <Tag color="blue">综合状态：{mental.overall_state ?? '未知'}</Tag>
              </div>
            ) : (
              <Empty description="暂无心智数据" />
            )}
          </Card>
        </Col>

        {/* 组合状态 */}
        <Col xs={24} sm={12}>
          <Card title={<><FundOutlined /> 组合状态</>} bordered={false}>
            {portfolio ? (
              <Row gutter={[16, 16]}>
                <Col span={8}>
                  <Statistic
                    title="偏离度"
                    value={portfolio.deviation ?? 0}
                    precision={2}
                    suffix="%"
                    valueStyle={{ color: (portfolio.deviation ?? 0) > 5 ? '#ff4d4f' : '#3f8600' }}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="最大回撤"
                    value={portfolio.max_drawdown ?? 0}
                    precision={2}
                    suffix="%"
                    valueStyle={{ color: '#cf1322' }}
                  />
                </Col>
                <Col span={8}>
                  <Statistic
                    title="夏普比率"
                    value={portfolio.sharpe_ratio ?? 0}
                    precision={2}
                    valueStyle={{ color: '#3f8600' }}
                  />
                </Col>
              </Row>
            ) : (
              <Empty description="暂无组合数据" />
            )}
          </Card>
        </Col>

        {/* 市场环境 */}
        <Col xs={24} sm={12}>
          <Card title={<><GlobalOutlined /> 市场环境</>} bordered={false}>
            {market ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <div>
                  <div style={{ marginBottom: 4 }}>A股情绪</div>
                  <Progress
                    percent={Math.round((market.a_shares ?? 0) * 100)}
                    strokeColor={stateColor(market.a_shares ?? 0)}
                  />
                </div>
                <div>
                  <div style={{ marginBottom: 4 }}>美股情绪</div>
                  <Progress
                    percent={Math.round((market.us_stocks ?? 0) * 100)}
                    strokeColor={stateColor(market.us_stocks ?? 0)}
                  />
                </div>
                <div>
                  <div style={{ marginBottom: 4 }}>港股情绪</div>
                  <Progress
                    percent={Math.round((market.hk_stocks ?? 0) * 100)}
                    strokeColor={stateColor(market.hk_stocks ?? 0)}
                  />
                </div>
              </div>
            ) : (
              <Empty description="暂无市场数据" />
            )}
          </Card>
        </Col>

        {/* 风险告警 */}
        <Col xs={24} sm={12}>
          <Card title={<><AlertOutlined /> 风险告警</>} bordered={false}>
            {risk ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Badge count={risk.total ?? 0} showZero offset={[6, 0]}>
                  <Statistic title="风险事件总数" value={risk.total ?? 0} />
                </Badge>
                <Row gutter={16}>
                  <Col span={12}>
                    <Statistic
                      title="严重事件"
                      value={risk.critical ?? 0}
                      valueStyle={{ color: '#ff4d4f' }}
                      prefix={<WarningOutlined />}
                    />
                  </Col>
                  <Col span={12}>
                    <Statistic
                      title="未解决"
                      value={risk.unresolved ?? 0}
                      valueStyle={{ color: '#faad14' }}
                    />
                  </Col>
                </Row>
              </div>
            ) : (
              <Empty description="暂无风险告警" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {/* 待确认事项 */}
        <Col xs={24} lg={12}>
          <Card title="待确认事项" bordered={false}>
            {pending.length > 0 ? (
              <List
                dataSource={pending}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      title={item.title}
                      description={item.description}
                    />
                    {item.type && <Tag color="blue">{item.type}</Tag>}
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="暂无待确认事项" />
            )}
          </Card>
        </Col>

        {/* 最近活动 */}
        <Col xs={24} lg={12}>
          <Card title="最近活动" bordered={false}>
            {activities.length > 0 ? (
              <Timeline
                items={activities.map((act, idx) => ({
                  key: idx,
                  children: (
                    <div>
                      <div>{act.description}</div>
                      <div style={{ color: 'rgba(0,0,0,0.45)', fontSize: 12 }}>
                        {act.actor ? `${act.actor} · ` : ''}
                        {dayjs(act.time).format('YYYY-MM-DD HH:mm:ss')}
                      </div>
                    </div>
                  ),
                }))}
              />
            ) : (
              <Empty description="暂无最近活动" />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
};

export default Home;
