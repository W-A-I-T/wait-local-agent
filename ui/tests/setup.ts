import "@testing-library/jest-dom/vitest";

// jsdom does not implement native modal lifecycle. Keyboard focus and inert
// background behavior are exercised with the actual browser in persona tests.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
};
