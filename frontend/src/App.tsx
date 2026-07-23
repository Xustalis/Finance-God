import React from 'react';
import { Routes, Route } from 'react-router-dom';
import AppLayout from './components/AppLayout';

const Home = React.lazy(() => import('./pages/Home'));
const Profile = React.lazy(() => import('./pages/Profile'));
const Mandate = React.lazy(() => import('./pages/Mandate'));
const Portfolio = React.lazy(() => import('./pages/Portfolio'));
const AgentCenter = React.lazy(() => import('./pages/AgentCenter'));
const Trading = React.lazy(() => import('./pages/Trading'));
const Review = React.lazy(() => import('./pages/Review'));

const App: React.FC = () => {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/mandate" element={<Mandate />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/agents" element={<AgentCenter />} />
        <Route path="/trading" element={<Trading />} />
        <Route path="/review" element={<Review />} />
      </Route>
    </Routes>
  );
};

export default App;
