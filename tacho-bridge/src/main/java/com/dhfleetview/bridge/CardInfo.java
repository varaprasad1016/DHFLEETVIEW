/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
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
