/* steamticket.exe - the stand account's Steam Encrypted App Ticket for Relic's lobby login (relic_scan.py, 03.11.2026).
 * Runs under Wine in the stand's prefix next to the game's own steam_api.dll (SteamUser014), app id from SteamAppId=56400.
 * The ticket is what DOW2.exe 3.19 itself sends (FUN_00632620 / FUN_006326f0): an Encrypted App Ticket requested with the
 * user data "RLINK" (ISteamUser::RequestEncryptedAppTicket, vtable +0x4c), then GetEncryptedAppTicket; the game base64s it
 * into platformlogin's auth (the scanner does that).
 * stdout: one line "OK <steamid64> <ticket hex>" (read by the scanner through a pipe - never logged, never on a command line),
 * then waits for stdin to close. Errors: "ERR <what>" and exit code 2.
 * Build: i686-w64-mingw32-gcc -O2 -s -static-libgcc -o steamticket.exe steamticket.c
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

typedef int  (__cdecl *init_t)(void);
typedef void (__cdecl *shutdown_t)(void);
typedef void *(__cdecl *user_t)(void);
typedef unsigned char (__attribute__((thiscall)) *blogged_t)(void *self);
typedef unsigned long long *(__attribute__((thiscall)) *steamid_t)(void *self, unsigned long long *ret);
typedef unsigned long long (__attribute__((thiscall)) *reqenc_t)(void *self, void *data, int cb);
typedef unsigned char (__attribute__((thiscall)) *getenc_t)(void *self, void *buf, int cb, unsigned int *pcb);
typedef void (__cdecl *runcb_t)(void);

/* ISteamUser014 vtable: 0 GetHSteamUser, 1 BLoggedOn, 2 GetSteamID, ... 19 RequestEncryptedAppTicket, 20 GetEncryptedAppTicket */
enum { V_LOGGED = 1, V_STEAMID = 2, V_REQENC = 19, V_GETENC = 20 };

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    HMODULE m = LoadLibraryA("steam_api.dll");
    if (!m) { printf("ERR steam_api.dll\n"); return 2; }
    init_t init = (init_t)GetProcAddress(m, "SteamAPI_Init");
    shutdown_t shut = (shutdown_t)GetProcAddress(m, "SteamAPI_Shutdown");
    user_t su = (user_t)GetProcAddress(m, "SteamUser");
    runcb_t runcb = (runcb_t)GetProcAddress(m, "SteamAPI_RunCallbacks");
    if (!init || !su || !shut || !runcb) { printf("ERR exports\n"); return 2; }
    if (!init()) { printf("ERR SteamAPI_Init\n"); return 2; }
    void *u = su();
    if (!u) { printf("ERR SteamUser\n"); shut(); return 2; }
    void **vt = *(void ***)u;
    if (!((blogged_t)vt[V_LOGGED])(u)) { printf("ERR not logged on\n"); shut(); return 2; }
    unsigned long long sid = 0;
    ((steamid_t)vt[V_STEAMID])(u, &sid);
    unsigned char buf[2048]; unsigned int n = 0; int ok = 0;
    ((reqenc_t)vt[V_REQENC])(u, "RLINK", 5);
    for (int i = 0; i < 300 && !ok; i++) {           /* up to 30 s for Steam's answer */
        Sleep(100); runcb();
        n = 0; ok = ((getenc_t)vt[V_GETENC])(u, buf, sizeof buf, &n) && n >= 16 && n <= sizeof buf;
    }
    if (!ok) { printf("ERR no encrypted app ticket\n"); shut(); return 2; }
    char hex[4100]; for (unsigned int i = 0; i < n; i++) sprintf(hex + 2 * i, "%02x", buf[i]);
    printf("OK %llu %s\n", sid, hex);
    char line[64];
    while (fgets(line, sizeof line, stdin)) {}
    shut();
    return 0;
}
