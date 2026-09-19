---
layout: default
title: Install wizard
---

<section class="wizard" id="install-wizard">
  <div class="wizard-header">
    <span class="eyebrow">Installation wizard</span>
    <h1>Set up JapyScope</h1>
    <div class="progress-label" id="progress-label" aria-live="polite"></div>
    <div class="progress" aria-hidden="true"><span id="progress-bar"></span></div>
  </div>

  <section class="wizard-step active">
    <h2>Before you start</h2>
    <p>You need an original Raspberry Pi Zero W (armv6), a reputable microSD card, and a stable 5V/2.5A power supply. A weak power supply or poor card can corrupt the system during installation.</p>
    <div class="step-options"><button class="step-option" data-answer="ready">I have the Pi Zero W, good power, and a reliable SD card.</button><a class="step-option" href="{{ '/install-reference/#power-and-sd-card-read-this-first' | relative_url }}">I need the full hardware requirements first.</a></div>
  </section>
  <section class="wizard-step">
    <h2>Choose the right operating system</h2>
    <p>Flash <strong>Raspberry Pi OS Bullseye/Bookworm Lite, 32-bit</strong> with Raspberry Pi Imager. Do not use 64-bit, Trixie, or a desktop image: the installer intentionally supports Bullseye/Bookworm armhf only.</p>
    <div class="step-options">
      <button class="step-option" data-answer="bullseye">I have selected Bullseye Lite, 32-bit.</button>
      <button class="step-option" data-answer="bookworm">I have selected Bookworm Lite, 32-bit.</button>
    </div>
    <p class="notice" id="os-note" hidden></p>
  </section>
  <section class="wizard-step">
    <h2>Prepare the Pi</h2>
    <p>In Raspberry Pi Imager, configure a user and enable SSH if you will not attach a keyboard. Flash the card, insert it, and boot the Pi.</p>
    <div class="step-options"><button class="step-option" data-answer="booted">The Pi has booted and I can access its terminal.</button></div>
  </section>
  <section class="wizard-step">
    <h2>Run the installer</h2>
    <p>Copy or clone this repository to the Pi, open its root directory, then run:</p>
    <pre><code>sudo install/install.sh</code></pre>
    <p>The installer sets up INDI, dependencies, Wi-Fi onboarding, system services, and daily OTA updates.</p>
    <div class="step-options"><button class="step-option" data-answer="installed">The installer completed without an error.</button></div>
  </section>
  <section class="wizard-step">
    <h2>Connect it to Wi-Fi</h2>
    <p>When no saved connection is active, join <strong>JapyScope-Setup</strong>. Its unique password appears on the controller. Browse to <code>http://192.168.4.1:8080/setup</code>, submit your home Wi-Fi details, then reconnect your phone or computer to that network.</p>
    <div class="step-options"><button class="step-option" data-answer="wifi">JapyScope is now connected to my network.</button></div>
  </section>
  <section class="wizard-step">
    <h2>Check that everything is running</h2>
    <p>Open the Web UI at <code>http://japyscope.local:8080/</code> (or the Pi’s IP address). Generate an access code on the controller under <strong>Menu → Wi-Fi / Web Access</strong>.</p>
    <pre><code>systemctl status japyscope-splash japyscope-app japyscope-webui</code></pre>
    <p class="notice">You’re ready for the software side. For errors or hardware validation notes, use the troubleshooting guide.</p>
    <p><a class="button" href="{{ '/troubleshooting/' | relative_url }}">Troubleshooting</a></p>
  </section>
  <div class="wizard-nav"><button class="secondary" id="previous-step" type="button">Previous</button><button id="next-step" type="button" disabled>Next</button></div>
</section>

<script>
  (() => {
    const steps = [...document.querySelectorAll('.wizard-step')];
    const previous = document.querySelector('#previous-step');
    const next = document.querySelector('#next-step');
    const label = document.querySelector('#progress-label');
    const bar = document.querySelector('#progress-bar');
    let current = 0;
    function render() {
      steps.forEach((step, index) => step.classList.toggle('active', index === current));
      previous.disabled = current === 0;
      next.textContent = current === steps.length - 1 ? 'Done' : 'Next';
      next.disabled = current < steps.length - 1 && !steps[current].querySelector('.selected');
      label.textContent = `Step ${current + 1} of ${steps.length}`;
      bar.style.width = `${((current + 1) / steps.length) * 100}%`;
    }
    const osNote = document.querySelector('#os-note');
    const osNotes = {
      bullseye: 'Bullseye uses the legacy wpa_supplicant/hostapd Wi-Fi path.',
      bookworm: 'Bookworm uses NetworkManager for both the saved Wi-Fi network and the setup hotspot.'
    };
    document.querySelectorAll('[data-answer]').forEach(button => button.addEventListener('click', () => {
      button.closest('.wizard-step').querySelectorAll('[data-answer]').forEach(option => option.classList.remove('selected'));
      button.classList.add('selected');
      next.disabled = false;
      if (osNotes[button.dataset.answer]) {
        osNote.textContent = osNotes[button.dataset.answer];
        osNote.hidden = false;
      }
    }));
    previous.addEventListener('click', () => { current = Math.max(0, current - 1); render(); });
    next.addEventListener('click', () => { if (current < steps.length - 1) { current += 1; render(); } });
    render();
  })();
</script>
