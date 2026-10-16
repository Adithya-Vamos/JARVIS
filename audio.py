def jarvis_loop():
    def background_startup():
        print("--- Brain self-check ---")
        check_brains()
        describe_browser()
        print("------------------------")
        start_reminders()

        if USE_WAKE_WORD:
            calibrate()
            if ALWAYS_LISTENING:
                speak("Jarvis is online. I am listening.")
            else:
                speak("Jarvis is online. Say Jarvis, then your command.")
        else:
            speak("Jarvis is online. How can I help?")

        if STARTED_BY_WINDOWS and STARTUP_BRIEFING:  # Jarvis was started by Windows: greet with the briefing
            try:
                speak(build_briefing())
            except Exception as e:
                print("Briefing error:", repr(e))

        if LOCAL_WAKE and USE_WAKE_WORD and not ALWAYS_LISTENING:
            init_local_wake()

    # Launch startup checks and greeting in the background so the HUD opens instantly without audio lag
    threading.Thread(target=background_startup, daemon=True).start()

    awake = False  # True during the follow-up window after an answer
    while True:
        try:
            quiet = STATE["lock"] and not STATE["woken"]
            if not USE_WAKE_WORD:
                HUD.state("listening")
                input("\nPress Enter, then speak: ")
                command = transcribe(record_until_silence(wait_seconds=8))
            elif quiet:
                HUD.state("standby")
                command = wait_for_quiet_wake()
                if command is None:
                    continue  # the mode changed: start listening the new way straight away
                STATE["woken"] = True  # you called it, so it may answer out loud
                HUD.state("listening")
                if not command:  # they only said "Hey Jarvis" - ask for the command
                    speak("Yes?")
                    command = strip_wake(transcribe(record_until_silence(wait_seconds=8)))
            elif awake or ALWAYS_LISTENING:
                HUD.state("listening")
                if STATE["lock"]:
                    seconds = QUIET_FOLLOW_UP_SECONDS
                elif ALWAYS_LISTENING:
                    seconds = None
                else:
                    seconds = FOLLOW_UP_SECONDS
                audio = record_until_silence(wait_seconds=seconds)
                if audio is None:
                    awake = False
                    STATE["woken"] = False
                    print("(sleeping - say Jarvis)")
                    continue
                HUD.state("thinking")
                command = strip_wake(transcribe(audio))
            else:
                HUD.state("idle")
                command = wait_for_wake_word()
                if command is None:
                    continue  # the mode changed: start listening the new way straight away
                HUD.state("listening")
                if not command:  # they only said "Jarvis" - ask for the command
                    speak("Yes?")
                    command = strip_wake(transcribe(record_until_silence(wait_seconds=8)))
        except (KeyboardInterrupt, EOFError):
            print("\nStopped.")
            break

        if not command:
            continue
        show(command, role="you")

        started = time.time()
        result = handle(command)
        print(f"[done in {time.time() - started:.1f}s]")
        if result == "quit":
            break
        if STATE["enter_quiet"]:  # Jarvis just opened something: go silent
            STATE["enter_quiet"] = False
            set_lock(True)
            awake = False
            print("(quiet mode - say Hey Jarvis)")
        elif result == "sleep":
            awake = False
            STATE["woken"] = False
        else:
            awake = True