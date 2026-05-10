import { Tabs, Typography } from "antd";
import PrivateLendingPanel from "./PrivateLendingPanel";
import RentalPanel from "./RentalPanel";
import { BG } from "./calcShared";
import "./App.css";

const { Title, Text } = Typography;

export default function App() {
  return (
    <div className="app-root" style={{ background: BG, minHeight: "100vh", padding: 24 }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <Title level={3} style={{ color: "#0F172A", marginBottom: 8 }}>
          法律金额计算（原型）
        </Title>
        <Text type="secondary">背景与主色遵循 UI 规范；请先启动后端 API（端口 8000）。</Text>

        <Tabs
          style={{ marginTop: 24 }}
          items={[
            {
              key: "lending",
              label: "民间借贷",
              children: <PrivateLendingPanel />,
            },
            {
              key: "rental",
              label: "房屋租赁",
              children: <RentalPanel />,
            },
          ]}
        />
      </div>
    </div>
  );
}
