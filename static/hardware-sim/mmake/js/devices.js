/* ============================================================
 * devices.js —— 拓展设备库（元数据 + SVG 图标 + 默认引脚）
 * ============================================================ */
(function (global) {
  'use strict';
  var ZKB = global.ZKB || (global.ZKB = {});

  /* 简易 SVG 图标（size = 像素边长） */
  var ICONS = {
    expboard: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="6" y="10" width="36" height="26" rx="3" fill="#3a414c"/>' +
        '<rect x="6" y="30" width="36" height="8" rx="3" fill="#c79a3a"/>' +
        '<rect x="10" y="14" width="10" height="6" rx="1" fill="#5b6775"/>' +
        '<circle cx="34" cy="17" r="3" fill="#ff5d5d"/>' +
        '<g fill="#e8c66a"><circle cx="10" cy="34" r="1.6"/><circle cx="16" cy="34" r="1.6"/><circle cx="22" cy="34" r="1.6"/><circle cx="28" cy="34" r="1.6"/><circle cx="34" cy="34" r="1.6"/></g>' +
        '<rect x="20" y="4" width="8" height="7" rx="1.5" fill="#8a93a0"/></svg>';
    },
    dht: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="12" y="6" width="24" height="32" rx="4" fill="#4a5563"/>' +
        '<rect x="17" y="11" width="14" height="14" rx="2" fill="#6fb7d6"/>' +
        '<g fill="#cfd6dd"><rect x="15" y="38" width="5" height="6"/><rect x="28" y="38" width="5" height="6"/></g>' +
        '<circle cx="32" cy="32" r="2.4" fill="#ffd08a"/></svg>';
    },
    ultrasonic: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="8" y="18" width="32" height="18" rx="3" fill="#3b424c"/>' +
        '<circle cx="16" cy="15" r="7" fill="#20252c" stroke="#6b7480" stroke-width="2"/>' +
        '<circle cx="32" cy="15" r="7" fill="#20252c" stroke="#6b7480" stroke-width="2"/>' +
        '<circle cx="16" cy="15" r="2.6" fill="#9fb4c8"/><circle cx="32" cy="15" r="2.6" fill="#9fb4c8"/>' +
        '<g stroke="#7ec8e3" stroke-width="1.4" fill="none" opacity=".7"><path d="M12 30 q-4 4 0 8"/><path d="M36 30 q4 4 0 8"/></g></svg>';
    },
    servo: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="8" y="16" width="32" height="22" rx="4" fill="#9aa3ad"/>' +
        '<circle cx="24" cy="27" r="9" fill="#c3cad3"/><circle cx="24" cy="27" r="3.4" fill="#5b6775"/>' +
        '<g style="transform-box:view-box;transform-origin:24px 17px;transition:transform .2s">' +
        '<rect x="22" y="4" width="4" height="14" rx="1.6" fill="#d9dee4"/>' +
        '<circle cx="24" cy="6" r="2.6" fill="#f0f2f5"/></g></svg>';
    },
    ir: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="10" y="12" width="28" height="24" rx="3" fill="#30363e"/>' +
        '<circle cx="18" cy="24" r="5.4" fill="#161a1f" stroke="#7d8794" stroke-width="1.6"/>' +
        '<circle cx="30" cy="24" r="5.4" fill="#161a1f" stroke="#7d8794" stroke-width="1.6"/>' +
        '<rect x="13" y="36" width="5" height="6" fill="#c79a3a"/><rect x="30" y="36" width="5" height="6" fill="#c79a3a"/>' +
        '<circle cx="24" cy="17" r="1.6" fill="#e0553a"/></svg>';
    },
    heater: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<circle cx="24" cy="24" r="15" fill="#d94a38"/>' +
        '<circle cx="24" cy="24" r="11" fill="#f0745f"/>' +
        '<path d="M19 24 a5 5 0 0 1 10 0 a5 5 0 0 1 -10 0 M24 19 v10" stroke="#ffe8d6" stroke-width="2.2" fill="none"/>' +
        '<rect x="22" y="39" width="4" height="5" fill="#8a93a0"/></svg>';
    },
    car: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="9" y="17" width="30" height="14" rx="3" fill="#3d7ea6"/>' +
        '<rect x="14" y="12" width="20" height="8" rx="2" fill="#5a9cbd"/>' +
        '<circle cx="15" cy="33" r="5.4" fill="#2b2f36"/><circle cx="33" cy="33" r="5.4" fill="#2b2f36"/>' +
        '<circle cx="15" cy="33" r="2.2" fill="#8a93a0"/><circle cx="33" cy="33" r="2.2" fill="#8a93a0"/>' +
        '<rect x="11" y="20" width="4" height="4" rx="1" fill="#ffe08a"/></svg>';
    },
    motor: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="12" y="14" width="20" height="22" rx="4" fill="#c2632c"/>' +
        '<circle cx="22" cy="25" r="7" fill="#e0834d"/><circle cx="22" cy="25" r="2.6" fill="#7a3d17"/>' +
        '<rect x="32" y="22" width="8" height="6" rx="2" fill="#9aa3ad"/>' +
        '<path class="motor-spin" style="transform-box:view-box;transform-origin:34px 25px" d="M40 18 l5 -3 v6 z" fill="#5b6775"/></svg>';
    },
    pump: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="10" y="18" width="24" height="18" rx="4" fill="#2f9e8e"/>' +
        '<circle cx="22" cy="27" r="6" fill="#7fd4c8"/>' +
        '<path d="M34 22 h6 M37 22 v10" stroke="#9aa3ad" stroke-width="3"/>' +
        '<path d="M16 12 c-3 4 0 6 0 6 s3 -2 0 -6z" fill="#4d9dff"/></svg>';
    },
    color: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="10" y="12" width="28" height="24" rx="3" fill="#4a4154"/>' +
        '<rect x="15" y="16" width="12" height="12" rx="2" fill="#f3f4f7"/>' +
        '<circle cx="21" cy="22" r="4" fill="#e8eef5"/>' +
        '<circle cx="33" cy="19" r="2.2" fill="#ff5d5d"/><circle cx="33" cy="25" r="2.2" fill="#3ddc84"/><circle cx="33" cy="31" r="2.2" fill="#4d9dff"/>' +
        '<rect x="13" y="36" width="5" height="6" fill="#c79a3a"/><rect x="30" y="36" width="5" height="6" fill="#c79a3a"/></svg>';
    },
    camera: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="8" y="10" width="32" height="28" rx="5" fill="#d83a30"/>' +
        '<circle cx="24" cy="24" r="9" fill="#1d2229"/><circle cx="24" cy="24" r="5.5" fill="#3a4450"/>' +
        '<circle cx="24" cy="24" r="2.6" fill="#7f93a8"/>' +
        '<circle cx="34" cy="15" r="1.8" fill="#ffd08a"/>' +
        '<rect x="21" y="38" width="6" height="4" fill="#8a93a0"/></svg>';
    },
    mic: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="13" y="10" width="22" height="22" rx="5" fill="#5b4a72"/>' +
        '<g stroke="#cbb9e0" stroke-width="1.4" opacity=".8"><line x1="18" y1="14" x2="18" y2="28"/><line x1="22" y1="13" x2="22" y2="29"/><line x1="26" y1="13" x2="26" y2="29"/><line x1="30" y1="14" x2="30" y2="28"/></g>' +
        '<path d="M16 26 q8 10 16 0" stroke="#cbb9e0" stroke-width="2" fill="none"/>' +
        '<rect x="22" y="33" width="4" height="7" fill="#8a93a0"/><rect x="18" y="39" width="12" height="3" rx="1.5" fill="#8a93a0"/></svg>';
    },
    lightExt: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="12" y="12" width="24" height="24" rx="3" fill="#7d7460"/>' +
        '<circle cx="24" cy="24" r="7" fill="#e8c66a"/>' +
        '<path d="M24 20 v8 M20 24 h8 M21 21 l6 6 M27 21 l-6 6" stroke="#8a6f1f" stroke-width="1.4"/>' +
        '<g stroke="#ffd96b" stroke-width="2"><line x1="24" y1="6" x2="24" y2="10"/><line x1="10" y1="24" x2="14" y2="24"/><line x1="34" y1="24" x2="38" y2="24"/><line x1="14" y1="14" x2="17" y2="17"/><line x1="34" y1="14" x2="31" y2="17"/></g></svg>';
    },
    /* —— 新增设备 —— */
    soil: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<path d="M14 8 L20 42 L28 42 L34 8 Z" fill="#8a6f3a"/>' +
        '<path d="M17 8 L20 30 L28 30 L31 8 Z" fill="#c9a85a"/>' +
        '<rect x="13" y="4" width="22" height="6" rx="2" fill="#5b6775"/>' +
        '<circle cx="24" cy="7" r="1.6" fill="#7fd4c8"/></svg>';
    },
    pm25: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="8" y="12" width="32" height="24" rx="4" fill="#5b6775"/>' +
        '<rect x="12" y="16" width="24" height="16" rx="2" fill="#e8eef5"/>' +
        '<g fill="#9aa3ad"><circle cx="18" cy="22" r="2.4"/><circle cx="26" cy="20" r="1.6"/>' +
        '<circle cx="30" cy="26" r="2"/><circle cx="22" cy="27" r="1.8"/>' +
        '<circle cx="17" cy="28" r="1.2"/></g>' +
        '<rect x="13" y="36" width="5" height="6" fill="#c79a3a"/><rect x="30" y="36" width="5" height="6" fill="#c79a3a"/></svg>';
    },
    baro: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<circle cx="24" cy="24" r="17" fill="#4a5563"/>' +
        '<circle cx="24" cy="24" r="13" fill="#e8eef5"/>' +
        '<path d="M24 14 A10 10 0 0 1 34 24" stroke="#d94a38" stroke-width="2.4" fill="none"/>' +
        '<line x1="24" y1="24" x2="33" y2="18" stroke="#2b2f36" stroke-width="2.2" stroke-linecap="round"/>' +
        '<circle cx="24" cy="24" r="2" fill="#2b2f36"/>' +
        '<rect x="20" y="39" width="8" height="4" rx="1.5" fill="#8a93a0"/></svg>';
    },
    button: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="8" y="10" width="32" height="28" rx="4" fill="#c2632c"/>' +
        '<rect x="12" y="14" width="24" height="20" rx="3" fill="#e0834d"/>' +
        '<circle cx="24" cy="24" r="8" fill="#ff5d5d" stroke="#b03a2f" stroke-width="1.5"/>' +
        '<circle cx="24" cy="24" r="3.4" fill="#ffb0a8"/></svg>';
    },
    fan: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<circle cx="24" cy="24" r="5" fill="#9aa3ad"/>' +
        '<g class="fan-spin" style="transform-box:view-box;transform-origin:24px 24px">' +
        '<path d="M24 24 Q14 6 12 16 Q14 22 24 24 Z" fill="#7ec8e3"/>' +
        '<path d="M24 24 Q42 14 32 12 Q26 14 24 24 Z" fill="#5aa8cc"/>' +
        '<path d="M24 24 Q34 42 36 32 Q34 26 24 24 Z" fill="#7ec8e3"/>' +
        '<path d="M24 24 Q6 34 16 36 Q22 34 24 24 Z" fill="#5aa8cc"/></g>' +
        '<circle cx="24" cy="24" r="2.4" fill="#2b2f36"/></svg>';
    },
    robot: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        /* 天线 */
        '<path d="M24 6 v5" stroke="#8a93a0" stroke-width="2.4" stroke-linecap="round"/>' +
        '<circle cx="24" cy="5" r="2.4" fill="#e0552c"/>' +
        /* 机身 */
        '<rect x="10" y="12" width="28" height="22" rx="6" fill="#f2f5f9" stroke="#b9c2ce" stroke-width="1.6"/>' +
        /* AI 摄像头眼 */
        '<circle cx="19" cy="21" r="4.2" fill="#1d2530"/><circle cx="19" cy="21" r="1.8" fill="#4a90d9"/>' +
        '<circle cx="29" cy="21" r="4.2" fill="#1d2530"/><circle cx="29" cy="21" r="1.8" fill="#4a90d9"/>' +
        /* 地面颜色传感器（巡线探头） */
        '<rect x="20" y="27" width="8" height="4" rx="1.6" fill="#3a4048"/>' +
        '<circle cx="24" cy="29" r="1.4" fill="#43c46f"/>' +
        /* 轮子 */
        '<circle cx="15" cy="38" r="5.4" fill="#26292e"/><circle cx="15" cy="38" r="2.2" fill="#5a6470"/>' +
        '<circle cx="33" cy="38" r="5.4" fill="#26292e"/><circle cx="33" cy="38" r="2.2" fill="#5a6470"/></svg>';
    },

    /* —— 通讯网络 —— */
    radio: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<circle cx="24" cy="30" r="5" fill="#7c5cd6"/>' +
        '<path d="M24 25 V14" stroke="#b5a4ee" stroke-width="2.6" stroke-linecap="round"/>' +
        '<g fill="none" stroke="#9d8ae8" stroke-width="2.4" stroke-linecap="round">' +
        '<path d="M15 22 a12 12 0 0 1 18 0"/>' +
        '<path d="M10.5 17 a19 19 0 0 1 27 0"/>' +
        '<path d="M19.5 26 a7 7 0 0 1 9 0" opacity=".7"/></g>' +
        '<circle cx="24" cy="9" r="2.4" fill="#b5a4ee"/></svg>';
    },
    wifi: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<g fill="none" stroke="#7c5cd6" stroke-width="3" stroke-linecap="round">' +
        '<path d="M10 18 a20 20 0 0 1 28 0"/>' +
        '<path d="M15 24 a13 13 0 0 1 18 0"/>' +
        '<path d="M20 30 a6 6 0 0 1 8 0"/></g>' +
        '<circle cx="24" cy="35" r="2.8" fill="#7c5cd6"/></svg>';
    },
    ntp: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<circle cx="24" cy="26" r="15" fill="none" stroke="#7c5cd6" stroke-width="2.6"/>' +
        '<path d="M24 17 v9 l7 4" stroke="#9d8ae8" stroke-width="2.4" stroke-linecap="round" fill="none"/>' +
        '<path d="M18 7 q6 -5 12 0" stroke="#b5a4ee" stroke-width="2.6" fill="none" stroke-linecap="round"/>' +
        '<path d="M33 5 l4 -2 l-1 5" fill="#9d8ae8"/></svg>';
    },
    mqtt: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<path d="M14 22 a8 8 0 0 1 15 -3 a7 7 0 0 1 8 9 a6 6 0 0 1 -7 7 H16 a7 7 0 0 1 -2 -13z" fill="#dfe6f5" stroke="#7c5cd6" stroke-width="2"/>' +
        '<text x="24" y="27" text-anchor="middle" font-size="11" font-weight="bold" fill="#7c5cd6">MQTT</text>' +
        '<g fill="none" stroke="#9d8ae8" stroke-width="2" stroke-linecap="round"><path d="M38 14 q5 2 2 7"/><path d="M42 10 q8 4 3 12"/></g>' +
        '<circle cx="10" cy="36" r="2.4" fill="#9d8ae8"/></svg>';
    },
    asr: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="19" y="7" width="10" height="20" rx="5" fill="#7c5cd6"/>' +
        '<path d="M14 24 q10 14 20 0" fill="none" stroke="#9d8ae8" stroke-width="2.4"/>' +
        '<path d="M24 31 v7 M19 38 h10" stroke="#9d8ae8" stroke-width="2.4" stroke-linecap="round"/>' +
        '<g stroke="#b5a4ee" stroke-width="2" stroke-linecap="round"><line x1="10" y1="18" x2="10" y2="28"/><line x1="6" y1="21" x2="6" y2="25"/><line x1="38" y1="18" x2="38" y2="28"/><line x1="42" y1="21" x2="42" y2="25"/></g></svg>';
    },
    weather: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<circle cx="18" cy="18" r="7" fill="#ffd76b"/>' +
        '<g stroke="#f0b429" stroke-width="2" stroke-linecap="round"><line x1="18" y1="4" x2="18" y2="8"/><line x1="18" y1="28" x2="18" y2="32"/><line x1="4" y1="18" x2="8" y2="18"/><line x1="28" y1="18" x2="32" y2="18"/></g>' +
        '<path d="M20 38 a8 8 0 0 1 1 -16 a10 10 0 0 1 19 4 a7 7 0 0 1 -2 12z" fill="#e8eef5" stroke="#7c5cd6" stroke-width="2"/></svg>';
    },

    /* —— 第二十九轮：八年级新增硬件 ——
       磁场传感器（板载 MMC5603NJ，I2C 地址 0x30）
       卫星定位 ATGM336H（UART）
       二维码（板载 OLED 点阵生成）
       RFID 射频卡（I2C）
       离线语音识别模块（UART） */
    magnetic: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<circle cx="24" cy="24" r="17" fill="#1e3a5f" stroke="#2f5a8f" stroke-width="2"/>' +
        '<circle cx="24" cy="24" r="12" fill="#f4f6f8"/>' +
        /* 指针：N 指向正上 */
        '<path d="M24 9 L29 26 L24 22 L19 26 Z" fill="#e0483e"/>' +
        '<path d="M24 39 L19 22 L24 26 L29 22 Z" fill="#b9c2ce"/>' +
        '<text x="24" y="7" font-size="7" font-weight="bold" fill="#1e3a5f" text-anchor="middle">N</text>' +
        '<circle cx="24" cy="24" r="2" fill="#1e3a5f"/>' +
        '<g fill="#c79a3a"><rect x="10" y="43" width="4" height="4"/><rect x="18" y="43" width="4" height="4"/>' +
        '<rect x="26" y="43" width="4" height="4"/><rect x="34" y="43" width="4" height="4"/></g></svg>';
    },
    gps: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        /* 卫星 */
        '<g transform="translate(24,10)"><rect x="-6" y="-5" width="12" height="10" rx="2" fill="#c3cad3"/>' +
        '<rect x="-7" y="-3" width="4" height="6" fill="#4d9dff"/><rect x="3" y="-3" width="4" height="6" fill="#4d9dff"/>' +
        '<path d="M-6,5 L-14,12 M6,5 L14,12" stroke="#8a93a0" stroke-width="1.6"/></g>' +
        /* 信号弧 */
        '<g fill="none" stroke="#7ec8e3" stroke-width="1.8" stroke-linecap="round" opacity=".8">' +
        '<path d="M14 20 a14 14 0 0 1 20 0"/><path d="M17 24 a10 10 0 0 1 14 0"/>' +
        '<path d="M20 28 a6 6 0 0 1 8 0"/></g>' +
        /* 定位针 */
        '<path d="M24 30 C18 30 14 34 14 39 a10 10 0 0 0 20 0 c0 -5 -4 -9 -10 -9z" fill="#2f7fb5"/>' +
        '<circle cx="24" cy="38" r="3.4" fill="#f4f6f8"/>' +
        '<g fill="#c79a3a"><rect x="9" y="44" width="4" height="4"/><rect x="17" y="44" width="4" height="4"/>' +
        '<rect x="27" y="44" width="4" height="4"/><rect x="35" y="44" width="4" height="4"/></g></svg>';
    },
    qrcode: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="4" y="4" width="40" height="40" rx="3" fill="#f4f6f8" stroke="#b9c2ce" stroke-width="1.4"/>' +
        /* 三个定位角 */
        '<g fill="#1d2530">' +
        '<path d="M8 8 h11v11h-3v-8h-8z"/><path d="M29 8 h11v11h-3v-8h-8z"/><path d="M8 29 h3v8h8v3h-11z"/>' +
        '<rect x="14" y="14" width="5" height="5"/><rect x="31" y="14" width="5" height="5"/>' +
        '<rect x="14" y="31" width="5" height="5"/></g>' +
        /* 数据点*/
        '<g fill="#1d2530">' +
        '<rect x="23" y="9" width="3" height="3"/><rect x="23" y="15" width="3" height="3"/>' +
        '<rect x="9" y="23" width="3" height="3"/><rect x="15" y="23" width="3" height="3"/>' +
        '<rect x="23" y="23" width="3" height="3"/><rect x="29" y="23" width="3" height="3"/>' +
        '<rect x="35" y="23" width="3" height="3"/><rect x="23" y="29" width="3" height="3"/>' +
        '<rect x="29" y="29" width="3" height="3"/><rect x="35" y="29" width="3" height="3"/>' +
        '<rect x="23" y="35" width="3" height="3"/><rect x="29" y="35" width="3" height="3"/>' +
        '<rect x="35" y="35" width="3" height="3"/></g></svg>';
    },
    rfid: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="6" y="14" width="24" height="20" rx="3" fill="#2b3038"/>' +
        '<circle cx="18" cy="24" r="6.5" fill="#0f1418" stroke="#5a636e" stroke-width="1.4"/>' +
        '<circle cx="18" cy="24" r="2.6" fill="#4a90d9"/>' +
        '<rect x="9" y="18" width="4" height="3" rx="1" fill="#3ddc84"/>' +
        '<g stroke="#7ec8e3" stroke-width="1.6" fill="none" opacity=".75">' +
        '<path d="M32 20 a6 6 0 0 1 0 8"/><path d="M36 16 a12 12 0 0 1 0 16"/><path d="M40 12 a18 18 0 0 1 0 24"/></g>' +
        /* 卡片 */
        '<rect x="33" y="28" width="11" height="7" rx="1.5" fill="#e8c66a" stroke="#a8842f" stroke-width="1"/>' +
        '<g fill="#c79a3a"><rect x="9" y="38" width="4" height="5"/><rect x="16" y="38" width="4" height="5"/>' +
        '<rect x="23" y="38" width="4" height="5"/></g></svg>';
    },
    speech2: function (s) {
      return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
        '<rect x="8" y="10" width="32" height="28" rx="4" fill="#3d2f5c"/>' +
        '<rect x="12" y="14" width="24" height="10" rx="2" fill="#1a1d21"/>' +
        '<text x="24" y="22" font-size="7" fill="#7fd4c8" text-anchor="middle" font-family="monospace">ASR</text>' +
        /* 麦克风 */
        '<rect x="20" y="27" width="8" height="7" rx="4" fill="#cbb9e0"/>' +
        '<path d="M16 32 q8 9 16 0" fill="none" stroke="#cbb9e0" stroke-width="1.8" stroke-linecap="round"/>' +
        '<g fill="#c79a3a"><rect x="12" y="38" width="4" height="5"/><rect x="19" y="38" width="4" height="5"/>' +
        '<rect x="26" y="38" width="4" height="5"/><rect x="33" y="38" width="4" height="5"/></g></svg>';
    }
  };

  /* 设备分类（用于拓展库筛选） */
  var CATS = {
    main: '主控', sensor: '传感器', actuator: '执行器', network: '通讯网络', other: '其他'
  };

  /* ============================================================
 * 新增硬件（依据 DFRobot 官方资料补充）
 * 巡线传感器 SEN0241 / 数字功率计 SEN0291 / AS7341 SEN0364
 * 红外发射 DFR0095 / 红外接收 DFR0094 / 继电器 DFR0017
 * 风扇 DFR0332 / 光线 DFR0026 / 温湿度 DFR0067 / 超声波 SEN0001
 * ============================================================ */
  ICONS.tracker = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="4" y="12" width="40" height="24" rx="3" fill="#1f242a" stroke="#3a414c"/>' +
      '<rect x="9" y="16" width="8" height="16" rx="1.5" fill="#0a0d10"/>' +
      '<rect x="20" y="16" width="8" height="16" rx="1.5" fill="#0a0d10"/>' +
      '<circle cx="35" cy="20" r="3" fill="#ff5d5d"/>' +
      '<circle cx="35" cy="28" r="3" fill="#4ade80"/>' +
      '<g fill="#c79a3a"><rect x="6" y="36" width="4" height="5"/><rect x="13" y="36" width="4" height="5"/>' +
      '<rect x="20" y="36" width="4" height="5"/><rect x="27" y="36" width="4" height="5"/></g></svg>';
  };
  ICONS.powerMeter = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="6" y="10" width="36" height="28" rx="3" fill="#1b3a52"/>' +
      '<rect x="11" y="15" width="26" height="12" rx="1.5" fill="#0b3d1f"/>' +
      '<text x="24" y="24" font-size="7" fill="#8cff9e" text-anchor="middle" font-family="monospace">2.4V</text>' +
      '<rect x="11" y="30" width="26" height="4" rx="2" fill="#0a2e18"/>' +
      '<rect x="11" y="30" width="16" height="4" rx="2" fill="#3fe07a"/>' +
      '<g fill="#c79a3a"><rect x="10" y="38" width="4" height="5"/><rect x="17" y="38" width="4" height="5"/>' +
      '<rect x="24" y="38" width="4" height="5"/><rect x="31" y="38" width="4" height="5"/></g></svg>';
  };
  ICONS.gravity = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="7" y="11" width="34" height="26" rx="3" fill="#3d2f5c"/>' +
      '<circle cx="24" cy="23" r="8" fill="#0f1418" stroke="#7c5cd6" stroke-width="1.6"/>' +
      '<circle cx="24" cy="23" r="3" fill="#c86ad0"/>' +
      '<g fill="#c79a3a"><rect x="11" y="37" width="4" height="5"/><rect x="18" y="37" width="4" height="5"/>' +
      '<rect x="25" y="37" width="4" height="5"/><rect x="32" y="37" width="4" height="5"/></g></svg>';
  };
  ICONS.irTx = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="10" y="14" width="28" height="20" rx="3" fill="#1f242a"/>' +
      '<circle cx="17" cy="24" r="5" fill="#3a1a1a" stroke="#ff3b30" stroke-width="1.4"/>' +
      '<circle cx="17" cy="24" r="2" fill="#ff3b30"/>' +
      '<g stroke="#ff3b30" stroke-width="1.4" fill="none" opacity=".7">' +
      '<path d="M23 20 q6 4 0 8"/><path d="M28 17 q9 7 0 14"/></g>' +
      '<g fill="#c79a3a"><rect x="13" y="34" width="4" height="5"/><rect x="20" y="34" width="4" height="5"/>' +
      '<rect x="27" y="34" width="4" height="5"/></g></svg>';
  };
  ICONS.irRx = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="12" y="14" width="24" height="20" rx="3" fill="#2b3038"/>' +
      '<circle cx="24" cy="24" r="7" fill="#14181d" stroke="#5a636e" stroke-width="1.4"/>' +
      '<circle cx="24" cy="24" r="3" fill="#2f3a44"/>' +
      '<g fill="#c79a3a"><rect x="15" y="34" width="4" height="5"/><rect x="22" y="34" width="4" height="5"/>' +
      '<rect x="29" y="34" width="4" height="5"/></g></svg>';
  };
  ICONS.ledModule = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="10" y="12" width="28" height="24" rx="3" fill="#2b3038"/>' +
      '<circle cx="24" cy="22" r="7" fill="#ffd24a"/>' +
      '<circle cx="24" cy="22" r="10" fill="none" stroke="#ffd24a" stroke-width="1" opacity=".5"/>' +
      '<g fill="#c79a3a"><rect x="13" y="36" width="4" height="5"/><rect x="20" y="36" width="4" height="5"/>' +
      '<rect x="27" y="36" width="4" height="5"/></g></svg>';
  };
  ICONS.rgbStrip = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="4" y="16" width="40" height="16" rx="3" fill="#1a1d21"/>' +
      '<g>' +
      '<rect x="8" y="20" width="5" height="8" rx="1.5" fill="#ff4d4d"/>' +
      '<rect x="15" y="20" width="5" height="8" rx="1.5" fill="#4ade80"/>' +
      '<rect x="22" y="20" width="5" height="8" rx="1.5" fill="#4d9dff"/>' +
      '<rect x="29" y="20" width="5" height="8" rx="1.5" fill="#f0b429"/>' +
      '<rect x="36" y="20" width="5" height="8" rx="1.5" fill="#c86ad0"/>' +
      '</g></svg>';
  };
  /* 第三十六轮：人体红外（PIR）与 MP3 模块图标 */
  ICONS.pir = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="12" y="8" width="24" height="30" rx="3" fill="#2b3038"/>' +
      '<circle cx="24" cy="20" r="7" fill="#3a4150"/>' +
      '<circle cx="24" cy="20" r="4" fill="#11151b"/>' +
      '<g fill="none" stroke="#ff8a5c" stroke-width="1.6" stroke-linecap="round">' +
      '<path d="M13 30a11 11 0 0 1 22 0" opacity=".85"/>' +
      '<path d="M9 33a15 15 0 0 1 30 0" opacity=".5"/>' +
      '</g>' +
      '<g fill="#c79a3a"><rect x="16" y="38" width="4" height="4"/>' +
      '<rect x="22" y="38" width="4" height="4"/><rect x="28" y="38" width="4" height="4"/></g></svg>';
  };
  ICONS.mp3 = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="6" y="14" width="36" height="24" rx="3" fill="#1f3a5c"/>' +
      '<circle cx="16" cy="26" r="7" fill="#0a0d10"/>' +
      '<circle cx="16" cy="26" r="3" fill="#5a6672"/>' +
      '<g fill="#3f88e8"><rect x="26" y="19" width="12" height="3" rx="1.5"/>' +
      '<rect x="26" y="25" width="12" height="3" rx="1.5"/>' +
      '<rect x="26" y="31" width="8" height="3" rx="1.5"/></g>' +
      '<circle cx="38" cy="17" r="2" fill="#4ade80"/></svg>';
  };
  ICONS.relay = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="6" y="10" width="36" height="28" rx="3" fill="#1f3a5c"/>' +
      '<rect x="12" y="14" width="14" height="14" rx="2" fill="#1a1d21"/>' +
      '<circle cx="19" cy="21" r="4" fill="#0a0d10"/>' +
      '<circle cx="35" cy="17" r="2.4" fill="#ff5d5d"/>' +
      '<g fill="#3fae5a"><rect x="31" y="23" width="8" height="4" rx="1"/>' +
      '<rect x="31" y="29" width="8" height="4" rx="1"/></g>' +
      '<g fill="#c79a3a"><rect x="10" y="38" width="4" height="5"/><rect x="17" y="38" width="4" height="5"/>' +
      '<rect x="24" y="38" width="4" height="5"/><rect x="31" y="38" width="4" height="5"/></g></svg>';
  };
  ICONS.angle = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<circle cx="24" cy="24" r="16" fill="#2f3740" stroke="#5a646e" stroke-width="1.6"/>' +
      '<circle cx="24" cy="24" r="11" fill="#1c2127"/>' +
      '<path d="M24 24 L24 12" stroke="#e0552c" stroke-width="2.4" stroke-linecap="round"/>' +
      '<circle cx="24" cy="24" r="2.6" fill="#c9d1d9"/>' +
      '<g fill="#c79a3a"><rect x="16" y="40" width="4" height="5"/><rect x="23" y="40" width="4" height="5"/>' +
      '<rect x="30" y="40" width="4" height="5"/></g></svg>';
  };
  ICONS.remote = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      '<rect x="8" y="8" width="32" height="32" rx="5" fill="#2b3038"/>' +
      '<g fill="#3a414c">' +
      '<rect x="12" y="12" width="8" height="8" rx="2"/><rect x="28" y="12" width="8" height="8" rx="2"/>' +
      '<rect x="12" y="24" width="8" height="8" rx="2"/><rect x="28" y="24" width="8" height="8" rx="2"/>' +
      '</g><circle cx="24" cy="8" r="2" fill="#ff5d5d"/></svg>';
  };

  /* 机器人模型（第十四轮）：舞台「机器人送餐 / 巡线机器人」情景的控制对象 */
  ICONS.robot = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      /* 托盘 + 餐盒 */
      '<rect x="12" y="4" width="24" height="4" rx="2" fill="#8a93a0"/>' +
      '<rect x="18" y="0" width="12" height="6" rx="2" fill="#f0b64a"/>' +
      /* 机身 */
      '<rect x="9" y="9" width="30" height="24" rx="6" fill="#f2f5f9" stroke="#b9c2ce" stroke-width="1.4"/>' +
      /* 摄像头眼 */
      '<rect x="27" y="13" width="10" height="8" rx="2.5" fill="#1d2530"/>' +
      '<circle cx="32" cy="17" r="2.6" fill="#4a90d9"/><circle cx="32" cy="17" r="1" fill="#bfe0ff"/>' +
      /* 地面颜色传感器 */
      '<rect x="13" y="14" width="10" height="7" rx="1.6" fill="#14181e"/>' +
      '<rect x="14" y="15" width="8" height="5" rx="1.2" fill="#26292e"/>' +
      /* 轮子 */
      '<circle cx="16" cy="35" r="6" fill="#26292e"/><circle cx="16" cy="35" r="2.4" fill="#5a6470"/>' +
      '<circle cx="32" cy="35" r="6" fill="#26292e"/><circle cx="32" cy="35" r="2.4" fill="#5a6470"/>' +
      '<g fill="#c79a3a"><rect x="19" y="39" width="4" height="5"/><rect x="26" y="39" width="4" height="5"/></g></svg>';
  };

  /* 巡线小车（第十四轮）：电机 + 循迹器探针 + 超声波 */
  ICONS.traceCar = function (s) {
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 48 48">' +
      /* 车体 */
      '<rect x="5" y="18" width="38" height="14" rx="4" fill="#2f7fb5" stroke="#20608c" stroke-width="1.4"/>' +
      '<rect x="12" y="13" width="18" height="7" rx="2.5" fill="#63b0dd"/>' +
      /* 超声波 */
      '<circle cx="40" cy="22" r="5" fill="#0d1014" stroke="#6b7480" stroke-width="1.6"/>' +
      '<circle cx="40" cy="22" r="2" fill="#1a1f25"/>' +
      /* 循迹器探针条（5 路） */
      '<rect x="6" y="32" width="26" height="7" rx="2" fill="#1f242a"/>' +
      '<g fill="#4ade80">' +
      '<rect x="8" y="34" width="3.6" height="3" rx="1"/><rect x="13" y="34" width="3.6" height="3" rx="1"/>' +
      '<rect x="18" y="34" width="3.6" height="3" rx="1"/><rect x="23" y="34" width="3.6" height="3" rx="1"/>' +
      '<rect x="28" y="34" width="3.6" height="3" rx="1"/></g>' +
      /* 轮子 */
      '<circle cx="13" cy="32" r="5.6" fill="#22262c"/><circle cx="13" cy="32" r="2.2" fill="#8a93a0"/>' +
      '<circle cx="35" cy="32" r="5.6" fill="#22262c"/><circle cx="35" cy="32" r="2.2" fill="#8a93a0"/>' +
      /* 电机 */
      '<circle cx="22" cy="20" r="4" fill="#cf7a16"/><circle cx="22" cy="20" r="1.6" fill="#7a3d17"/></svg>';
  };

  /* ---------------- 设备清单 ---------------- */
  ZKB.DEVICE_LIST = [
    { id: 'dht', name: '温湿度传感器', desc: 'DHT11 数字温湿度', pins: ['P1'], cat: 'sensor' },
    { id: 'ultrasonic', name: '超声波传感器', desc: 'HCSR04 测距', pins: ['Trig P14', 'Echo P13'], cat: 'sensor' },
    { id: 'servo', name: '舵机', desc: 'SG90 0~180°', pins: ['P0'], cat: 'actuator' },
    { id: 'ir', name: '红外传感器', desc: '障碍物检测', pins: ['P21'], cat: 'sensor' },
    { id: 'heater', name: '加热元件', desc: 'PWM 调功率', pins: ['P9'], cat: 'actuator' },
    { id: 'car', name: '小车模型', desc: '四驱/两驱小车', pins: ['P8', 'P16', 'P19', 'P20'], cat: 'actuator' },
    { id: 'motor', name: '直流电机', desc: '正反转 / 调速', pins: ['P6', 'P7'], cat: 'actuator' },
    { id: 'pump', name: '水泵', desc: '开关 / 调速', pins: ['P11'], cat: 'actuator' },
    { id: 'color', name: '颜色传感器', desc: 'TCS34725（I2C）', pins: ['I2C_3V3_A/B', 'I2C_5V'], cat: 'sensor' },
    { id: 'camera', name: 'AI 摄像头', desc: 'AI 视觉识别（UART）', pins: ['P13', 'P14'], cat: 'sensor' },
    { id: 'mic', name: '麦克风', desc: '模拟量声音采集', pins: ['P3'], cat: 'sensor' },
    { id: 'lightExt', name: '光线传感器', desc: '模拟量光照强度', pins: ['P2'], cat: 'sensor' },
    /* —— 以下为依据 DFRobot 资料新增的硬件 —— */
    { id: 'tracker', name: '巡线传感器', desc: 'SEN0241 巡线&光感（5 路）', pins: ['P13', 'P14'], cat: 'sensor' },
    { id: 'gravity', name: 'AS7341 颜色', desc: 'SEN0364 可见光颜色（I2C）', pins: ['I2C 5V'], cat: 'sensor' },
    { id: 'powerMeter', name: '数字功率计', desc: 'SEN0291 I2C 功率计', pins: ['I2C 5V'], cat: 'sensor' },
    { id: 'angle', name: '角度传感器', desc: '模拟角度电位器', pins: ['P2'], cat: 'sensor' },
    { id: 'irTx', name: '红外发射模块', desc: 'DFR0095 红外发射', pins: ['P16'], cat: 'actuator' },
    { id: 'irRx', name: '红外接收模块', desc: 'DFR0094 红外接收', pins: ['P15'], cat: 'sensor' },
    { id: 'ledModule', name: 'LED 模块', desc: '单色 LED 亮度控制', pins: ['P13'], cat: 'actuator' },
    { id: 'rgbStrip', name: 'RGB 灯带', desc: '全彩灯带（PWM 混色）', pins: ['P13'], cat: 'actuator' },
    { id: 'relay', name: '数字继电器', desc: 'DFR0017 继电器模块', pins: ['P8'], cat: 'actuator' },
    { id: 'remote', name: '红外遥控器', desc: '迷你遥控器（需配红外接收）', pins: ['P15'], cat: 'other' },
    /* 新增 */
    { id: 'soil', name: '土壤湿度传感器', desc: '测量土壤水分', pins: ['P10'], cat: 'sensor' },
    { id: 'pm25', name: 'PM2.5 传感器', desc: '空气质量检测', pins: ['P22', 'P23'], cat: 'sensor' },
    { id: 'baro', name: '气压传感器', desc: '测量大气压强', pins: ['I2C_5V'], cat: 'sensor' },
    { id: 'button', name: '按键模块', desc: '外接轻触按键', pins: ['P15'], cat: 'sensor' },
    /* 第三十六轮：新增人体红外传感器与 MP3 模块 */
    { id: 'pir', name: '人体红外', desc: 'PIR 人体感应（检测有人/无人）', pins: ['P15'], cat: 'sensor' },
    { id: 'mp3', name: 'MP3 模块', desc: 'DFRobot UART 音乐模块', pins: ['P13', 'P14'], cat: 'other' },
    { id: 'fan', name: '风扇', desc: 'PWM 调速风扇', pins: ['P16'], cat: 'actuator' },
    /* —— 第十四轮：机器人模型 / 巡线小车 —— */
    {
      id: 'robot', name: '机器人模型', desc: '巡线机器人（电机 + 循迹器 + 超声波 + 摄像头）',
      pins: ['M1', 'M2'], cat: 'other'
    },
    {
      id: 'traceCar', name: '巡线小车', desc: '小车电机 + 循迹器 5 路探针 + 超声波',
      pins: ['M1', 'M2'], cat: 'actuator'
    },
    /* —— 通讯网络（物联网） —— */
    { id: 'radio', name: '无线广播', desc: '掌控板无线广播通讯', pins: ['2.4G'], cat: 'network' },
    { id: 'wifi', name: 'WiFi', desc: 'WiFi 网络与热点通信', pins: ['板载'], cat: 'network' },
    { id: 'ntp', name: 'NTP', desc: 'NTP 网络时间同步', pins: ['互联网'], cat: 'network' },
    { id: 'mqtt', name: 'MQTT', desc: 'MQTT 物联网消息通讯', pins: ['互联网'], cat: 'network' },
    { id: 'asr', name: 'WiFi语音识别', desc: '语音识别成文字指令', pins: ['麦克风'], cat: 'network' },
    { id: 'weather', name: '天气', desc: '获取各地实时天气预报', pins: ['互联网'], cat: 'network' },
    /* —— 第二十九轮：八年级新增硬件（对应官方 hunan_* 积木） —— */
    {
      id: 'magnetic', name: '磁场传感器', desc: '板载磁力计MMC5603NJ（I2C 0x30），可测方位角',
      pins: ['I2C_5V'], cat: 'sensor'
    },
    {
      id: 'gps', name: '卫星定位模块', desc: 'ATGM336H 北斗 GPS（UART），经纬度 / 高度',
      pins: ['P13', 'P15'], cat: 'sensor'
    },
    {
      id: 'qrcode', name: '二维码', desc: '在OLED 上生成二维码（板载，无需接线）',
      pins: ['板载'], cat: 'other'
    },
    {
      id: 'rfid', name: 'RFID 射频卡', desc: 'I2C 射频卡读写，识别卡号',
      pins: ['I2C_5V'], cat: 'sensor'
    },
    {
      id: 'speech2', name: '离线语音识别', desc: '离线语音识别模块（UART），无需联网',
      pins: ['P13', 'P15'], cat: 'sensor'
    }
  ];

  ZKB.DEVICE_CATS = CATS;

  ZKB.deviceIcon = function (id, size) {
    return ICONS[ZKB.baseOf(id)] ? ICONS[ZKB.baseOf(id)](size || 40) : '';
  };
  ZKB.deviceMeta = function (id) {
    var base = ZKB.baseOf(id);
    for (var i = 0; i < ZKB.DEVICE_LIST.length; i++) {
      if (ZKB.DEVICE_LIST[i].id === base) return ZKB.DEVICE_LIST[i];
    }
    return null;
  };

  /* ============================================================
   * 实例 id 助手（历史数据兼容）
   *   第十四轮起：传感器 / 执行器每类仅可添加 1 个，设备名不再带序号。
   *   baseOf / instNo / instId 保留，用于兼容旧工程与旧连接数据中的
   *   motor__2 等多实例 id（读取时一律归并到基础 id）。
   * ============================================================ */
  ZKB.baseOf = function (id) {
    return String(id || '').split('__')[0];
  };
  ZKB.instNo = function (id) {
    var m = /__(\d+)$/.exec(String(id || ''));
    return m ? parseInt(m[1], 10) : 1;
  };
  /* 由基础 id + 序号 → 实例 id */
  ZKB.instId = function (base, n) {
    return (n && n > 1) ? base + '__' + n : base;
  };
  /* 该设备类型是否允许添加多个（第十四轮：全部设备均只允许 1 个） */
  ZKB.multipliable = function (id) {
    return false;
  };
  /* 显示名：设备名不带序号（直流电机 / 超声波传感器 …） */
  ZKB.deviceName = function (id) {
    var meta = ZKB.deviceMeta(id);
    return meta ? meta.name : String(id || '');
  };

})(window);
