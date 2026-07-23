import React, { useEffect, useState } from 'react';
import {
  Card,
  Spin,
  Steps,
  Form,
  Input,
  InputNumber,
  Select,
  Slider,
  Button,
  Row,
  Col,
  Descriptions,
  Progress,
  message,
  Drawer,
  Tag,
  Typography,
  Space,
} from 'antd';
import { SaveOutlined, EditOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { getProfile, saveProfile, confirmProfile } from '../../api/profile';
import ConfidenceBadge from '../../components/ConfidenceBadge';
import VersionTag from '../../components/VersionTag';
import type { UserProfile } from '../../types';

const { Title, Text, Paragraph } = Typography;

const currencyOptions = [
  { value: 'CNY', label: '人民币 (CNY)' },
  { value: 'USD', label: '美元 (USD)' },
  { value: 'HKD', label: '港币 (HKD)' },
];
const regionOptions = [
  { value: 'CN', label: '中国大陆' },
  { value: 'US', label: '美国' },
  { value: 'HK', label: '中国香港' },
];
const priorityOptions = [
  { value: 'high', label: '高' },
  { value: 'medium', label: '中' },
  { value: 'low', label: '低' },
];
const riskPreferenceOptions = [
  { value: 'conservative', label: '保守型' },
  { value: 'moderate', label: '稳健型' },
  { value: 'aggressive', label: '进取型' },
];
const reviewFreqOptions = [
  { value: 'daily', label: '每日' },
  { value: 'weekly', label: '每周' },
  { value: 'monthly', label: '每月' },
  { value: 'quarterly', label: '每季度' },
];
const drawdownReactionOptions = [
  { value: 'hold', label: '坚持持有' },
  { value: 'reduce', label: '减仓观望' },
  { value: 'add', label: '逢低加仓' },
];
const autonomyOptions = [
  { value: 'L0', label: 'L0 全手动' },
  { value: 'L1', label: 'L1 建议确认' },
  { value: 'L2', label: 'L2 限额自动' },
  { value: 'L3', label: 'L3 完全授权' },
];

const wizardSteps = [
  '基础信息',
  '理财目标',
  '财务约束',
  '风险偏好',
  '行为偏好',
  '投资限制',
  '预览确认',
];

const Profile: React.FC = () => {
  const [profile, setProfile] = useState<UserProfile | null | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [current, setCurrent] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => {
    getProfile()
      .then((p) => setProfile(p ?? null))
      .catch(() => setProfile(null))
      .finally(() => setLoading(false));
  }, []);

  const handleFinish = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload = {
        goals: values.goals ?? [],
        financial_constraints: {
          investable_amount: values.investable_amount,
          emergency_fund: values.emergency_fund,
          near_term_cash_needs: values.near_term_cash_needs,
          base_currency: values.base_currency,
          region: values.region,
        },
        stated_risk: {
          loss_tolerance: values.loss_tolerance,
          volatility_tolerance: values.volatility_tolerance,
          experience_years: values.experience_years,
          preference: values.preference,
        },
        behavioral_prefs: {
          review_frequency: values.review_frequency,
          drawdown_reaction: values.drawdown_reaction,
          autonomy_preference: values.autonomy_preference,
        },
        restrictions: {
          regions: values.restriction_regions,
          product_exclusions: values.product_exclusions,
        },
      };
      const saved = await saveProfile(payload);
      message.success('画像已保存');
      setProfile(saved);
    } catch (err) {
      if ((err as { errorFields?: unknown }).errorFields) return;
      message.error('保存失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleConfirm = async (version: number) => {
    try {
      const confirmed = await confirmProfile(version);
      message.success('画像已确认');
      setProfile(confirmed);
    } catch {
      message.error('确认失败，请检查完整度');
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  // ---------- 无画像：7 步向导 ----------
  if (!profile) {
    const completeness = Math.round(
      (((current >= 0 ? 1 : 0) + (current >= 1 ? 1 : 0) + (current >= 2 ? 1 : 0) + (current >= 3 ? 1 : 0) + (current >= 4 ? 1 : 0) + (current >= 5 ? 1 : 0) + (current >= 6 ? 1 : 0)) / 7) * 100,
    );
    return (
      <div>
        <Title level={4}>完善投资画像</Title>
        <Card>
          <Steps current={current} items={wizardSteps.map((t) => ({ title: t }))} />
          <div style={{ marginTop: 24 }}>
            <Form form={form} layout="vertical">
              {/* Step1 基础信息 */}
              {current === 0 && (
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="base_currency" label="基础货币" rules={[{ required: true, message: '请选择基础货币' }]}>
                      <Select options={currencyOptions} placeholder="请选择" />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="region" label="所在地区" rules={[{ required: true, message: '请选择地区' }]}>
                      <Select options={regionOptions} placeholder="请选择" />
                    </Form.Item>
                  </Col>
                </Row>
              )}

              {/* Step2 理财目标 */}
              {current === 1 && (
                <Form.List name="goals" initialValue={[{ name: '', target_amount: 0, target_date: '', priority: 'medium' }]}>
                  {(fields, { add, remove }) => (
                    <>
                      {fields.map((field) => (
                        <Row key={field.key} gutter={8} align="middle">
                          <Col span={6}>
                            <Form.Item name={[field.name, 'name']} label="目标名称">
                              <Input placeholder="如：退休储备" />
                            </Form.Item>
                          </Col>
                          <Col span={5}>
                            <Form.Item name={[field.name, 'target_amount']} label="目标金额">
                              <InputNumber style={{ width: '100%' }} min={0} />
                            </Form.Item>
                          </Col>
                          <Col span={5}>
                            <Form.Item name={[field.name, 'target_date']} label="目标日期">
                              <Input placeholder="YYYY-MM-DD" />
                            </Form.Item>
                          </Col>
                          <Col span={5}>
                            <Form.Item name={[field.name, 'priority']} label="优先级">
                              <Select options={priorityOptions} />
                            </Form.Item>
                          </Col>
                          <Col span={3}>
                            <Button type="link" danger onClick={() => remove(field.name)}>删除</Button>
                          </Col>
                        </Row>
                      ))}
                      <Button type="dashed" onClick={() => add({ name: '', target_amount: 0, target_date: '', priority: 'medium' })}>
                        + 添加目标
                      </Button>
                    </>
                  )}
                </Form.List>
              )}

              {/* Step3 财务约束 */}
              {current === 2 && (
                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item name="investable_amount" label="可投资金额" rules={[{ required: true }]}>
                      <InputNumber style={{ width: '100%' }} min={0} />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item name="emergency_fund" label="应急资金">
                      <InputNumber style={{ width: '100%' }} min={0} />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item name="near_term_cash_needs" label="短期现金需求">
                      <InputNumber style={{ width: '100%' }} min={0} />
                    </Form.Item>
                  </Col>
                </Row>
              )}

              {/* Step4 风险偏好 */}
              {current === 3 && (
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="loss_tolerance" label="亏损容忍度（最大可接受亏损比例）" rules={[{ required: true }]}>
                      <Slider min={0} max={1} step={0.05} marks={{ 0: '0%', 0.2: '20%', 0.5: '50%', 1: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="volatility_tolerance" label="波动容忍度" rules={[{ required: true }]}>
                      <Slider min={0} max={1} step={0.05} marks={{ 0: '低', 0.5: '中', 1: '高' }} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="experience_years" label="投资经验（年）" rules={[{ required: true }]}>
                      <InputNumber style={{ width: '100%' }} min={0} />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="preference" label="风险偏好" rules={[{ required: true }]}>
                      <Select options={riskPreferenceOptions} placeholder="请选择" />
                    </Form.Item>
                  </Col>
                </Row>
              )}

              {/* Step5 行为偏好 */}
              {current === 4 && (
                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item name="review_frequency" label="复盘频率" rules={[{ required: true }]}>
                      <Select options={reviewFreqOptions} placeholder="请选择" />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item name="drawdown_reaction" label="回撤反应" rules={[{ required: true }]}>
                      <Select options={drawdownReactionOptions} placeholder="请选择" />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item name="autonomy_preference" label="自主授权偏好" rules={[{ required: true }]}>
                      <Select options={autonomyOptions} placeholder="请选择" />
                    </Form.Item>
                  </Col>
                </Row>
              )}

              {/* Step6 投资限制 */}
              {current === 5 && (
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="restriction_regions" label="限制地区">
                      <Select mode="multiple" options={regionOptions} placeholder="选择要排除的地区" />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="product_exclusions" label="排除产品类型">
                      <Select
                        mode="tags"
                        placeholder="如：杠杆ETF、虚拟货币"
                      />
                    </Form.Item>
                  </Col>
                </Row>
              )}

              {/* Step7 预览 */}
              {current === 6 && (
                <div>
                  <Progress percent={completeness} status={completeness >= 60 ? 'success' : 'active'} />
                  <Paragraph type="secondary" style={{ marginTop: 8 }}>
                    完整度达到 60% 以上方可确认画像。
                  </Paragraph>
                  <Descriptions title="画像预览" bordered column={2} size="small" style={{ marginTop: 16 }}>
                    <Descriptions.Item label="基础货币">{form.getFieldValue('base_currency') ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="所在地区">{form.getFieldValue('region') ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="可投资金额">{form.getFieldValue('investable_amount') ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="风险偏好">{form.getFieldValue('preference') ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="复盘频率">{form.getFieldValue('review_frequency') ?? '-'}</Descriptions.Item>
                    <Descriptions.Item label="回撤反应">{form.getFieldValue('drawdown_reaction') ?? '-'}</Descriptions.Item>
                  </Descriptions>
                </div>
              )}
            </Form>

            <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
              <Button disabled={current === 0} onClick={() => setCurrent(current - 1)}>
                上一步
              </Button>
              {current < wizardSteps.length - 1 ? (
                <Button type="primary" onClick={() => setCurrent(current + 1)}>
                  下一步
                </Button>
              ) : (
                <Button type="primary" icon={<SaveOutlined />} loading={submitting} onClick={handleFinish}>
                  保存画像
                </Button>
              )}
            </div>
          </div>
        </Card>
      </div>
    );
  }

  // ---------- 有画像：维度展示 ----------
  const fc = profile.financial_constraints ?? {};
  const sr = profile.stated_risk ?? {};
  const bp = profile.behavioral_prefs ?? {};
  const rest = profile.restrictions ?? {};

  return (
    <div>
      <Row justify="space-between" align="middle">
        <Col>
          <Space>
            <Title level={4} style={{ marginBottom: 0 }}>我的投资画像</Title>
            <VersionTag version={profile.version} timestamp={profile.created_at ?? undefined} />
            <ConfidenceBadge value={profile.confidence ?? 0} />
            <Tag color={profile.status === 'confirmed' ? 'green' : 'default'}>{profile.status}</Tag>
          </Space>
        </Col>
        <Col>
          <Space>
            <Button icon={<EditOutlined />} onClick={() => setDrawerOpen(true)}>修正画像</Button>
            {profile.status !== 'confirmed' && (
              <Button
                type="primary"
                icon={<CheckCircleOutlined />}
                disabled={(profile.completeness ?? 0) < 0.6}
                onClick={() => handleConfirm(profile.version)}
              >
                确认画像
              </Button>
            )}
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={8}>
          <Card title="理财目标" bordered={false}>
            {(profile.goals ?? []).length > 0 ? (
              profile.goals.map((g, i) => (
                <div key={i} style={{ marginBottom: 8 }}>
                  <Text strong>{g.name}</Text>
                  <br />
                  <Text type="secondary">目标 {g.target_amount} · 日期 {g.target_date}</Text>
                  <Tag color={g.priority === 'high' ? 'red' : g.priority === 'medium' ? 'orange' : 'default'} style={{ marginLeft: 8 }}>
                    {g.priority}
                  </Tag>
                </div>
              ))
            ) : (
              <Text type="secondary">暂无目标</Text>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="财务约束" bordered={false}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="可投资金额">{fc.investable_amount ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="应急资金">{fc.emergency_fund ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="短期现金需求">{fc.near_term_cash_needs ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="基础货币">{fc.base_currency ?? '-'}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="风险偏好" bordered={false}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="亏损容忍度">{Math.round((sr.loss_tolerance ?? 0) * 100)}%</Descriptions.Item>
              <Descriptions.Item label="波动容忍度">{Math.round((sr.volatility_tolerance ?? 0) * 100)}%</Descriptions.Item>
              <Descriptions.Item label="投资经验">{sr.experience_years ?? 0} 年</Descriptions.Item>
              <Descriptions.Item label="偏好类型">{sr.preference ?? '-'}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="行为偏好" bordered={false}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="复盘频率">{bp.review_frequency ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="回撤反应">{bp.drawdown_reaction ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="自主授权偏好">{bp.autonomy_preference ?? '-'}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card title="投资限制" bordered={false}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="限制地区">
                {(rest.regions ?? []).map((r) => <Tag key={r}>{r}</Tag>)}
              </Descriptions.Item>
              <Descriptions.Item label="排除产品">
                {(rest.product_exclusions ?? []).map((p) => <Tag key={p} color="orange">{p}</Tag>)}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      <Card title="心智状态与置信度" bordered={false} style={{ marginTop: 16 }}>
        <Row gutter={16} align="middle">
          <Col span={8}>
            <div>画像完整度</div>
            <Progress percent={Math.round((profile.completeness ?? 0) * 100)} />
          </Col>
          <Col span={8}>
            <div>置信度</div>
            <Progress percent={Math.round((profile.confidence ?? 0) * 100)} />
          </Col>
          <Col span={8}>
            <ConfidenceBadge value={profile.confidence ?? 0} />
          </Col>
        </Row>
      </Card>

      <Drawer
        title="修正画像"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={400}
        extra={
          <Button
            type="primary"
            onClick={async () => {
              setDrawerOpen(false);
              setProfile(null);
              setCurrent(0);
              form.resetFields();
            }}
          >
            重新填写
          </Button>
        }
      >
        <Paragraph type="secondary">
          重新填写画像将创建新版本。当前版本 v{profile.version} 将被标记为已替代。
        </Paragraph>
      </Drawer>
    </div>
  );
};

export default Profile;
