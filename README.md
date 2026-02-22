# CactusCon 14 Badge Game

This repository contains the firmware for the CactusCon 14 conference badge: a small ESP32-S3 handheld built for in-person play. The goal was a game you could understand in minutes, play in short bursts between talks, and break into (if you wanted to).

The badge centers on creatures you carry with you through the event. You can meet other attendees, and challenge them for experience point to progress your creatures. You can also interact with station-style encounters that act like structured opponents or checkpoints around the venue, which reward you with new creature types if you win.

You can find the hardware repository with STLs for the Battery and Optional Back Cover, along with all the KiCad files and Schematics below:
- [BadgePiratesLLC/CactusCon14](https://github.com/BadgePiratesLLC/CactusCon14)

## The Badge Lifecycle and Game Loop

1. Register a handle on the badge.
2. Get a random starting creature and keep using the badge throughout the conference.
3. Discover nearby players or stations over BLE and initiate a battle.
4. Win or lose, your badge saves your state locally so the game continues offline.
5. Complete SAO hardware or CTF challenges to get codes for use in the game.
6. Peer up with other attendee badge holders to create chat sessions to exchange messages between devices.

Battles are designed to be quick. The firmware uses a deterministic battle flow so two badges can agree on the same outcome even with jittery radios, brief disconnects, and prevents most types of abuse from modified-badges.

## What The Firmware Provides

The firmware is a touch-first UI and a set of embedded subsystems that support the game:

- UI panels for character views, matchmaking, battle flow, settings, and utility screens
- BLE protocol for discovery, challenge/accept flows, turn-based battle exchange, and chat peering
- local persistence for player settings, progression, and session state
- optional WiFi-assisted features for registration, messaging, and update delivery when connectivity exists

This repo includes additional libraries as submodules; they are treated as dependencies that provide specific functionality (API communication, OTA update mechanics) and maintain their own documentation.

## Hardware Target

The firmware targets an ESP32-S3 badge with:

- 16MB+ flash, and 2MB+ psram
- a TFT display with touch input
- neopixel LEDs
- BLE for local badge-to-badge gameplay
- WiFi for network-assisted flows
- persistent on-device storage for settings and progression

## Developer Notes

The badge code, folder structure, flashing utilities, and development helpers are documented in `badge/README.md`.
