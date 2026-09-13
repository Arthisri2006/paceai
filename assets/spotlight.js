// One listener for the entire page; never tied to model work or app reruns.
if (!window.__paceSpotlightInstalled) {
  window.__paceSpotlightInstalled = true;
  document.addEventListener('pointermove', (event) => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const card = event.target.closest('[data-spotlight], [class*="st-key-topic_"]');
    if (!card) return;
    const rect = card.getBoundingClientRect();
    card.style.setProperty('--spot-x', `${event.clientX - rect.left}px`);
    card.style.setProperty('--spot-y', `${event.clientY - rect.top}px`);
  }, { passive: true });
}
