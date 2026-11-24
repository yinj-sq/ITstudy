/**
 * EmptyState - 空数据提示组件
 * 显示图标 + 提示文字，用于列表/表格无数据时的占位提示
 */
const EmptyState = {
  name: 'EmptyState',
  template: `
    <div class="flex flex-col items-center justify-center py-16 text-gray-400">
      <i :class="['fas', icon, 'text-5xl mb-4 text-gray-300']"></i>
      <p class="text-lg text-gray-500">{{ message }}</p>
      <slot></slot>
    </div>
  `,
  props: {
    message: {
      type: String,
      default: '暂无数据'
    },
    icon: {
      type: String,
      default: 'fa-inbox'
    }
  },
  setup() {
    return {};
  }
};
