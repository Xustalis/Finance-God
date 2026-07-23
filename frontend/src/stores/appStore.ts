import { create } from 'zustand';
import { getDashboard } from '../api/dashboard';
import type { DashboardData } from '../types';

interface AppState {
  dashboardData: DashboardData | null;
  loading: boolean;
  fetchDashboard: () => Promise<void>;
}

const useAppStore = create<AppState>((set) => ({
  dashboardData: null,
  loading: false,
  fetchDashboard: async () => {
    set({ loading: true });
    try {
      const data = await getDashboard();
      set({ dashboardData: data });
    } finally {
      set({ loading: false });
    }
  },
}));

export default useAppStore;
