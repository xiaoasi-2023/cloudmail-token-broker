import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#d46936",
          colorInfo: "#d46936",
          colorSuccess: "#3f7e68",
          colorWarning: "#c98a32",
          colorError: "#b84a43",
          colorText: "#202724",
          colorTextSecondary: "#68716d",
          colorBgContainer: "#fffdf8",
          colorBgLayout: "#ecece5",
          borderRadius: 4,
          fontFamily: "'IBM Plex Sans', 'Noto Sans SC', sans-serif",
          controlHeight: 38,
        },
        components: {
          Button: { fontWeight: 600 },
          Card: { boxShadowTertiary: "none" },
          Menu: { itemBorderRadius: 3 },
          Table: { headerBg: "#f1f1ea", headerColor: "#39413d" },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
);
