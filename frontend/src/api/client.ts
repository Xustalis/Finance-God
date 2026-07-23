import axios, { AxiosError } from 'axios';
import { message } from 'antd';

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

client.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ message?: string; error?: { message?: string } }>) => {
    const status = error.response?.status;
    const data = error.response?.data;
    // 后端统一格式: { success, error: { code, message, details } }
    const msg =
      data?.error?.message ||
      data?.message ||
      error.message ||
      '请求失败';
    if (status === 401) {
      localStorage.removeItem('token');
      message.error('登录已过期，请重新登录');
    } else {
      message.error(msg);
    }
    return Promise.reject(error);
  },
);

export default client;
