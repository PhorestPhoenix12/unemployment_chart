const tooltip = document.getElementById('tooltip');
document.querySelectorAll('path').forEach(state => {
  state.addEventListener('mousemove', e => {
    const value = state.getAttribute('data-inflation');
    tooltip.style.left = e.pageX + 10 + 'px';
    tooltip.style.top = e.pageY + 10 + 'px';
    tooltip.style.display = 'block';
    tooltip.innerHTML = `${state.id}: ${value}`;
  });
  state.addEventListener('mouseleave', () => {
    tooltip.style.display = 'none';
  });
});
