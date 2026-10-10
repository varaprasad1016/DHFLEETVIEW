/*
 * Copyright 2026 DH FleetView contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.traccar.tachograph.card;

import java.util.Date;

/**
 * Identity of the company card sitting in a bridge's reader, read from the card's
 * {@code EF_Identification} file.
 *
 * <p>Operators need this for two reasons: to confirm the right company's card is fitted before a
 * download runs, and to be warned before the card expires — an expired company card silently
 * stops every scheduled download in the fleet.
 */
public class CardIdentity {

    private String cardNumber;
    private Integer issuingMemberState;
    private String issuingAuthority;
    private String companyName;
    private String companyAddress;
    private Date issueDate;
    private Date validityBegin;
    private Date expiryDate;

    public String getCardNumber() {
        return cardNumber;
    }

    public void setCardNumber(String cardNumber) {
        this.cardNumber = cardNumber;
    }

    public Integer getIssuingMemberState() {
        return issuingMemberState;
    }

    public void setIssuingMemberState(Integer issuingMemberState) {
        this.issuingMemberState = issuingMemberState;
    }

    public String getIssuingAuthority() {
        return issuingAuthority;
    }

    public void setIssuingAuthority(String issuingAuthority) {
        this.issuingAuthority = issuingAuthority;
    }

    public String getCompanyName() {
        return companyName;
    }

    public void setCompanyName(String companyName) {
        this.companyName = companyName;
    }

    public String getCompanyAddress() {
        return companyAddress;
    }

    public void setCompanyAddress(String companyAddress) {
        this.companyAddress = companyAddress;
    }

    public Date getIssueDate() {
        return issueDate;
    }

    public void setIssueDate(Date issueDate) {
        this.issueDate = issueDate;
    }

    public Date getValidityBegin() {
        return validityBegin;
    }

    public void setValidityBegin(Date validityBegin) {
        this.validityBegin = validityBegin;
    }

    public Date getExpiryDate() {
        return expiryDate;
    }

    public void setExpiryDate(Date expiryDate) {
        this.expiryDate = expiryDate;
    }

    /** Whether the card is outside its validity window right now. */
    public boolean isExpired() {
        Date now = new Date();
        if (expiryDate != null && expiryDate.before(now)) {
            return true;
        }
        return validityBegin != null && validityBegin.after(now);
    }

    /** Days until the card expires, or null when the expiry date is unknown. */
    public Long getDaysUntilExpiry() {
        if (expiryDate == null) {
            return null;
        }
        long millis = expiryDate.getTime() - System.currentTimeMillis();
        return millis / (24L * 60 * 60 * 1000);
    }
}
