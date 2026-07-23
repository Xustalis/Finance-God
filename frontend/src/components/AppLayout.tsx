import React, { Suspense, useState } from 'react';
import { Layout, Menu, Avatar, Dropdown, Spin } from 'antd';
import type { MenuProps } from 'antd';
import {
  HomeOutlined,
  UserOutlined,
  SafetyCertificateOutlined,
  FundOutlined,
  RobotOutlined,
  StockOutlined,
  HistoryOutlined,
  LogoutOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import useAuthStore from '../stores/authStore';

const { Header, Sider, Content } = Layout;

const menuItems: MenuProps['items'] = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  { key: '/profile', icon: <UserOutlined />, label: '认识我' },
  { key: '/mandate', icon: <SafetyCertificateOutlined />, label: '我的授权' },
  { key: '/portfolio', icon: <FundOutlined />, label: '我的组合' },
  { key: '/agents', icon: <RobotOutlined />, label: 'Agent中心' },
  { key: '/trading', icon: <StockOutlined />, label: '交易' },
  { key: '/review', icon: <HistoryOutlined />, label: '复盘' },
];

const AppLayout: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);

  const handleMenuClick: MenuProps['onClick'] = ({ key }) => {
    navigate(key);
  };

  const handleUserMenuClick: MenuProps['onClick'] = ({ key }) => {
    if (key === 'profile') {
      navigate('/profile');
    } else if (key === 'logout') {
      logout();
      navigate('/');
    }
  };

  const userMenuItems: MenuProps['items'] = [
    { key: 'profile', icon: <UserOutlined />, label: '个人中心' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' },
  ];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div
          style={{
            height: 32,
            margin: 16,
            color: '#fff',
            textAlign: 'center',
            fontSize: 18,
            fontWeight: 'bold',
            lineHeight: '32px',
          }}
        >
          {collapsed ? 'FG' : 'Finance God'}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={handleMenuClick}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            alignItems: 'center',
            padding: '0 24px',
            background: '#fff',
          }}
        >
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <span style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', gap: 8 }}>
              <Avatar icon={<UserOutlined />} />
              <span>{user?.username ?? '用户'}</span>
            </span>
          </Dropdown>
        </Header>
        <Content
          style={{
            margin: 24,
            padding: 24,
            background: '#fff',
            borderRadius: 8,
            minHeight: 280,
          }}
        >
          <Suspense
            fallback={
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  height: '60vh',
                }}
              >
                <Spin size="large" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  );
};

export default AppLayout;
