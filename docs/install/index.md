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
    <div class="step-options"><button class="step-option" data-answer="ready" data-gate>I have the Pi Zero W, good power, and a reliable SD card.</button><a class="step-option" href="{{ '/install-reference/#power-and-sd-card-read-this-first' | relative_url }}">I need the full hardware requirements first.</a></div>
  </section>
  <section class="wizard-step">
    <h2>Choose the right operating system</h2>
    <p>Flash <strong>Raspberry Pi OS Bullseye/Bookworm/Trixie Lite, 32-bit</strong> with Raspberry Pi Imager. Do not use a 64-bit or desktop image: the installer intentionally supports Bullseye/Bookworm/Trixie armhf only.</p>
    <div class="step-options">
      <button class="step-option" data-answer="bullseye" data-gate>I have selected Bullseye Lite, 32-bit.</button>
      <button class="step-option" data-answer="bookworm" data-gate>I have selected Bookworm Lite, 32-bit.</button>
      <button class="step-option" data-answer="trixie" data-gate>I have selected Trixie Lite, 32-bit.</button>
    </div>
    <p class="notice" data-note hidden></p>
  </section>
  <section class="wizard-step">
    <h2>Prepare the Pi</h2>
    <p>In Raspberry Pi Imager, configure a user and enable SSH if you will not attach a keyboard. Flash the card, insert it, and boot the Pi.</p>
    <div class="step-options"><button class="step-option" data-answer="booted" data-gate>The Pi has booted and I can access its terminal.</button></div>
  </section>
  <section class="wizard-step">
    <h2>Run the installer</h2>
    <p>Copy or clone this repository to the Pi and open its root directory. Is this Pi's Wi-Fi already working — credentials set in Raspberry Pi Imager, or a wired connection?</p>
    <div class="step-options">
      <button class="step-option" data-answer="ap">Not yet — I'll join the setup hotspot to configure it.</button>
      <button class="step-option" data-answer="no-ap">Yes — don't bother starting a hotspot for it.</button>
    </div>
    <pre><code data-command>sudo install/install.sh</code></pre>
    <p class="notice" data-note hidden></p>
    <div class="step-options"><button class="step-option" data-answer="installed" data-gate>The installer completed without an error.</button><a class="step-option" href="{{ '/troubleshooting/' | relative_url }}">With error — help!</a></div>
  </section>
  <section class="wizard-step">
    <h2>Connect it to Wi-Fi</h2>
    <p>When no saved connection is active, join <strong>JapyScope-Setup</strong>. Its unique password appears on the controller. Browse to <code>http://192.168.4.1:8080/setup</code>, submit your home Wi-Fi details, then reconnect your phone or computer to that network.</p>
    <p class="notice" id="wifi-hint" hidden>Wi-Fi was already working before you even installed, so there's nothing to do here — JapyScope should already be on your network. Skip ahead.</p>
    <div class="step-options"><button class="step-option" data-answer="wifi" data-gate>JapyScope is now connected to my network.</button></div>
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
      next.disabled = current < steps.length - 1 && !steps[current].querySelector('[data-gate].selected');
      label.textContent = `Step ${current + 1} of ${steps.length}`;
      bar.style.width = `${((current + 1) / steps.length) * 100}%`;
    }
    // Notes and install commands are keyed by data-answer, and only ever
    // apply within the wizard-step of the button that set them — answer
    // values are unique across the whole wizard, so one map covers all steps.
    const notes = {
      bullseye: 'Bullseye uses the legacy wpa_supplicant/hostapd Wi-Fi path.',
      bookworm: 'Bookworm uses NetworkManager for both the saved Wi-Fi network and the setup hotspot.',
      trixie: 'Trixie uses NetworkManager, same as Bookworm, for both the saved Wi-Fi network and the setup hotspot.',
      ap: 'The installer sets up the JapyScope-Setup hotspot and starts it automatically at boot until it sees a known network.',
      'no-ap': "--no-ap only turns off that automatic boot-time check — the hotspot itself still gets installed, and Menu → Wi-Fi / Web Access or the Web UI's System page can start it by hand any time you do need to change networks."
    };
    const commands = { ap: 'sudo install/install.sh', 'no-ap': 'sudo install/install.sh --no-ap' };
    const wifiHint = document.querySelector('#wifi-hint');
    document.querySelectorAll('[data-answer]').forEach(button => button.addEventListener('click', () => {
      button.closest('.step-options').querySelectorAll('[data-answer]').forEach(option => option.classList.remove('selected'));
      button.classList.add('selected');
      if (button.hasAttribute('data-gate')) next.disabled = false;
      const answer = button.dataset.answer;
      const note = button.closest('.wizard-step').querySelector('[data-note]');
      if (note && notes[answer]) { note.textContent = notes[answer]; note.hidden = false; }
      const command = button.closest('.wizard-step').querySelector('[data-command]');
      if (command && commands[answer]) command.textContent = commands[answer];
      if (answer === 'no-ap') wifiHint.hidden = false;
      if (answer === 'ap') wifiHint.hidden = true;
    }));
    previous.addEventListener('click', () => { current = Math.max(0, current - 1); render(); });
    next.addEventListener('click', () => { if (current < steps.length - 1) { current += 1; render(); } });
    render();
  })();
</script>
