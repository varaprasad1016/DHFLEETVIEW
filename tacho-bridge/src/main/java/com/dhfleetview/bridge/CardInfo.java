package com.dhfleetview.bridge;

import java.util.Date;

/**
 * Non-sensitive card metadata. Never contains PIN, private keys or raw APDU payloads.
 */
public class CardInfo {
    public String cardIdentifier;
    public String cardType;
    public String issuingAuthority;
    public Date validityTo;
    public String status;
}
