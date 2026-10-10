// The welcome story decorates the introduction; it never creates simulation state.
const welcome = document.querySelector('#welcome-page');
const account = document.querySelector('.welcome-account');
const accountButton = document.querySelector('#welcome-account-button');
const accountPanel = document.querySelector('#welcome-account-panel');
const signInDialog = document.querySelector('#welcome-sign-in-dialog');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const compact = matchMedia('(max-width: 760px)');
const chapters = [...document.querySelectorAll('[data-story-chapter]')];
const scenes = [...document.querySelectorAll('[data-story-scene]')];
const jumps = [...document.querySelectorAll('[data-story-jump]')];
const story = document.querySelector('.welcome-story');
let frame = 0;
let activeChapter = -1;

function closeAccount(restoreFocus = false) {
  accountPanel.hidden = true;
  accountButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus) accountButton.focus();
}
accountButton.addEventListener('click', () => {
  const opening = accountPanel.hidden;
  accountPanel.hidden = !opening;
  accountButton.setAttribute('aria-expanded', String(opening));
});
accountButton.addEventListener('keydown', event => {
  if (event.key === 'ArrowDown') {
    event.preventDefault();
    accountPanel.hidden = false;
    accountButton.setAttribute('aria-expanded', 'true');
    accountPanel.querySelector('button').focus();
  }
});
account.addEventListener('focusout', event => {
  if (!account.contains(event.relatedTarget)) closeAccount();
});
document.addEventListener('click', event => {
  if (!account.contains(event.target)) closeAccount();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !accountPanel.hidden) closeAccount(true);
});
document.querySelector('#welcome-sign-in').addEventListener('click', () => {
  closeAccount();
  signInDialog.showModal();
});
document.querySelector('#welcome-sign-in-close').addEventListener('click', () => signInDialog.close());
document.querySelector('#welcome-sign-in-continue').addEventListener('click', () => signInDialog.close());
signInDialog.addEventListener('close', () => {
  if (!welcome.hidden) accountButton.focus();
});
signInDialog.addEventListener('click', event => {
  if (event.target !== signInDialog) return;
  const rect = signInDialog.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) signInDialog.close();
});

function selectChapter(index) {
  if (activeChapter === index) return;
  activeChapter = index;
  chapters.forEach((chapter, i) => chapter.classList.toggle('is-current', i === index));
  scenes.forEach((scene, i) => {
    scene.classList.toggle('is-current', i === index);
    scene.setAttribute('aria-hidden', String(i !== index));
  });
  jumps.forEach((jump, i) => {
    if (i === index) jump.setAttribute('aria-current', 'step');
    else jump.removeAttribute('aria-current');
  });
}
function updateStory() {
  frame = 0;
  if (welcome.hidden || document.body.dataset.view !== 'welcome') return;
  const anchor = innerHeight * .48;
  let nearest = 0, distance = Infinity;
  chapters.forEach((chapter, i) => {
    const rect = chapter.getBoundingClientRect();
    const next = Math.abs(rect.top + rect.height / 2 - anchor);
    if (next < distance) { distance = next; nearest = i; }
  });
  selectChapter(nearest);
  const bounds = story.getBoundingClientRect();
  // A restrained 28px drift, with no scroll capture or automatic navigation.
  const offset = reducedMotion.matches || compact.matches ? 0 : Math.max(-14, Math.min(14, (innerHeight / 2 - bounds.top) * .035 - 14));
  story.style.setProperty('--story-drift', `${offset.toFixed(2)}px`);
}
function scheduleStory() {
  if (!frame) frame = requestAnimationFrame(updateStory);
}
jumps.forEach((jump, i) => jump.addEventListener('click', () => {
  chapters[i].scrollIntoView({ block: 'center', behavior: reducedMotion.matches ? 'instant' : 'smooth' });
  chapters[i].focus({ preventScroll: true });
  selectChapter(i);
}));
window.addEventListener('scroll', scheduleStory, { passive: true });
window.addEventListener('resize', scheduleStory);
reducedMotion.addEventListener('change', scheduleStory);
compact.addEventListener('change', scheduleStory);
new MutationObserver(() => {
  if (document.body.dataset.view !== 'welcome') {
    closeAccount();
    if (signInDialog.open) signInDialog.close();
  }
  scheduleStory();
}).observe(document.body, { attributes: true, attributeFilter: ['data-view'] });
scheduleStory();
